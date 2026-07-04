from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from btc_trading_bot.config import Settings
from btc_trading_bot.futures_simulator import (
    FuturesSimulatorSettings,
    SimulatedTrade,
    _load,
    _resolve_symbols,
    _simulate_symbol_trades,
)
from btc_trading_bot.history import HistoryStore, HistoryStoreError
from btc_trading_bot.indicators import IndicatorError

FrameProvider = Callable[[str], tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]]

DEFAULT_THRESHOLDS = (0.55, 0.65, 0.75)
DEFAULT_STOPS = (0.010, 0.015, 0.020)
DEFAULT_RATIOS = (1.5, 2.0, 3.0)


@dataclass(frozen=True, slots=True)
class ParameterSet:
    entry_threshold: float
    stop_loss_percent: float
    reward_to_risk: float

    def label(self) -> str:
        return (
            f"threshold={self.entry_threshold:.2f} "
            f"stop={self.stop_loss_percent:.3f} "
            f"rr={self.reward_to_risk:.1f}"
        )


@dataclass(frozen=True, slots=True)
class WindowStats:
    trades: int
    wins: int
    win_rate: float | None
    net_r: float | None
    net_pnl: float


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold: int
    train_start: datetime
    test_start: datetime
    test_end: datetime
    chosen: ParameterSet
    train: WindowStats
    test: WindowStats
    baseline_test: WindowStats


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    exchange: str
    symbols: tuple[str, ...]
    primary_timeframe: str
    generated_at: datetime
    grid_size: int
    baseline: ParameterSet
    folds: tuple[FoldResult, ...]
    oos: WindowStats
    baseline_oos: WindowStats
    errors: tuple[str, ...] = ()


class WalkForwardError(RuntimeError):
    """Raised when walk-forward evaluation cannot run."""


def run_walk_forward(
    frame_provider: FrameProvider,
    *,
    exchange: str,
    symbols: Sequence[str],
    settings: Settings,
    simulator_settings: FuturesSimulatorSettings,
    grid: Sequence[ParameterSet],
    folds: int = 4,
    test_days: int = 21,
    train_days: int = 90,
    min_train_trades: int = 8,
) -> WalkForwardReport:
    """Rolling train/validate evaluation of signal parameters.

    Each parameter set is replayed once over the full candle history per
    symbol; folds then compare parameter sets on their train window and score
    the winner on the following unseen test window. Positions that span a
    window boundary are attributed to their entry window, a small and
    conservative approximation that keeps the replay cost linear in the grid
    size instead of folds x grid.
    """
    if folds < 2:
        raise WalkForwardError("At least 2 folds are required")
    baseline = ParameterSet(
        entry_threshold=simulator_settings.entry_threshold,
        stop_loss_percent=settings.stop_loss_percent,
        reward_to_risk=settings.reward_to_risk,
    )
    unique_grid = list(dict.fromkeys((*grid, baseline)))

    frames: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    errors: list[str] = []
    for symbol in symbols:
        try:
            frames[symbol] = frame_provider(symbol)
        except (HistoryStoreError, ValueError) as exc:
            errors.append(f"{symbol}: {exc}")
    if not frames:
        raise WalkForwardError(
            "No symbol candle history available: " + "; ".join(errors)
        )

    trades_by_params: dict[ParameterSet, list[SimulatedTrade]] = {}
    for params in unique_grid:
        pooled: list[SimulatedTrade] = []
        for symbol, (primary, daily, hourly) in frames.items():
            try:
                pooled.extend(
                    _simulate_symbol_trades(
                        symbol,
                        primary,
                        daily,
                        hourly,
                        replace(
                            settings,
                            stop_loss_percent=params.stop_loss_percent,
                            reward_to_risk=params.reward_to_risk,
                        ),
                        replace(
                            simulator_settings,
                            entry_threshold=params.entry_threshold,
                        ),
                    )
                )
            except (IndicatorError, ValueError) as exc:
                errors.append(f"{symbol} [{params.label()}]: {exc}")
        pooled.sort(key=lambda trade: trade.entry_time)
        trades_by_params[params] = pooled

    last_time = max(
        (
            _as_datetime(primary.iloc[-1]["timestamp"])
            for primary, _, _ in frames.values()
            if len(primary)
        ),
        default=None,
    )
    if last_time is None:
        raise WalkForwardError("Candle history is empty")

    fold_results: list[FoldResult] = []
    for fold_index in range(folds):
        offset = folds - fold_index
        test_end = last_time - timedelta(days=test_days * (offset - 1))
        test_start = test_end - timedelta(days=test_days)
        train_start = test_start - timedelta(days=train_days)

        best_params = baseline
        best_score: float | None = None
        best_train = _window_stats(
            trades_by_params[baseline], train_start, test_start
        )
        for params, trades in trades_by_params.items():
            train = _window_stats(trades, train_start, test_start)
            if train.trades < min_train_trades or train.net_r is None:
                continue
            if best_score is None or train.net_r > best_score:
                best_score = train.net_r
                best_params = params
                best_train = train

        fold_results.append(
            FoldResult(
                fold=fold_index + 1,
                train_start=train_start,
                test_start=test_start,
                test_end=test_end,
                chosen=best_params,
                train=best_train,
                test=_window_stats(
                    trades_by_params[best_params], test_start, test_end
                ),
                baseline_test=_window_stats(
                    trades_by_params[baseline], test_start, test_end
                ),
            )
        )

    oos = _merge_stats([fold.test for fold in fold_results])
    baseline_oos = _merge_stats([fold.baseline_test for fold in fold_results])
    return WalkForwardReport(
        exchange=exchange,
        symbols=tuple(frames.keys()),
        primary_timeframe=simulator_settings.primary_timeframe,
        generated_at=datetime.now(timezone.utc),
        grid_size=len(unique_grid),
        baseline=baseline,
        folds=tuple(fold_results),
        oos=oos,
        baseline_oos=baseline_oos,
        errors=tuple(errors),
    )


def format_walk_forward_report(report: WalkForwardReport) -> str:
    lines = [
        f"Walk-forward evaluation: {report.exchange} "
        f"{', '.join(report.symbols)} @ {report.primary_timeframe}",
        f"Grid: {report.grid_size} parameter sets; "
        f"baseline {report.baseline.label()}",
        "",
    ]
    for fold in report.folds:
        lines.append(
            f"Fold {fold.fold}: train {fold.train_start:%Y-%m-%d} -> "
            f"{fold.test_start:%Y-%m-%d}, test -> {fold.test_end:%Y-%m-%d}"
        )
        lines.append(
            f"  chosen [{fold.chosen.label()}] "
            f"train: {_stats_text(fold.train)}"
        )
        lines.append(f"  test (out-of-sample): {_stats_text(fold.test)}")
        lines.append(f"  baseline on same test: {_stats_text(fold.baseline_test)}")
    lines.append("")
    lines.append(f"Pooled out-of-sample (chosen params): {_stats_text(report.oos)}")
    lines.append(f"Pooled out-of-sample (baseline):      {_stats_text(report.baseline_oos)}")
    if report.errors:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  {error}" for error in report.errors[:8])
    lines.append("")
    lines.append(
        "Candle-only replay of public history; in-sample selection can still "
        "overfit, so judge parameters by the pooled out-of-sample row."
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(
        description=(
            "Rolling walk-forward parameter evaluation over local candle history"
        )
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=_env_path("BOT_HISTORY_DB_PATH"),
        help="SQLite history path, defaults to BOT_HISTORY_DB_PATH",
    )
    parser.add_argument(
        "--exchange",
        default=os.getenv("BOT_EXCHANGE", "binance-usdm"),
    )
    parser.add_argument(
        "--symbols",
        default=os.getenv("BOT_SYMBOLS") or os.getenv("BOT_SYMBOL", "BTC/USDT"),
        help="Comma-separated symbols",
    )
    parser.add_argument("--primary-timeframe", default=settings.entry_timeframe)
    parser.add_argument("--daily-timeframe", default=settings.daily_timeframe)
    parser.add_argument("--entry-timeframe", default=settings.entry_timeframe)
    parser.add_argument("--limit", type=int, default=8000)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--test-days", type=int, default=21)
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--min-train-trades", type=int, default=8)
    parser.add_argument("--horizon-hours", type=int, default=settings.paper_setup_horizon_hours)
    parser.add_argument("--fee-rate", type=float, default=0.0004)
    parser.add_argument("--funding-rate-8h", type=float, default=0.0)
    parser.add_argument("--leverage", type=int, default=settings.futures_leverage)
    parser.add_argument(
        "--thresholds",
        default=",".join(str(value) for value in DEFAULT_THRESHOLDS),
        help="Comma-separated entry-threshold candidates",
    )
    parser.add_argument(
        "--stops",
        default=",".join(str(value) for value in DEFAULT_STOPS),
        help="Comma-separated stop-loss-percent candidates",
    )
    parser.add_argument(
        "--ratios",
        default=",".join(str(value) for value in DEFAULT_RATIOS),
        help="Comma-separated reward-to-risk candidates",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.db_path is None:
        print("Set BOT_HISTORY_DB_PATH or pass --db-path.", file=sys.stderr)
        return 2
    symbols = [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    if not symbols:
        print("At least one symbol is required.", file=sys.stderr)
        return 2

    settings = replace(Settings.from_env(), futures_leverage=max(1, args.leverage))
    simulator_settings = FuturesSimulatorSettings(
        primary_timeframe=args.primary_timeframe,
        daily_timeframe=args.daily_timeframe,
        entry_timeframe=args.entry_timeframe,
        row_limit=max(200, args.limit),
        horizon_hours=max(1, args.horizon_hours),
        entry_threshold=settings.buy_threshold,
        taker_fee_rate=max(0.0, args.fee_rate),
        funding_rate_8h=args.funding_rate_8h,
    )
    grid = [
        ParameterSet(threshold, stop, ratio)
        for threshold in _parse_floats(args.thresholds, DEFAULT_THRESHOLDS)
        for stop in _parse_floats(args.stops, DEFAULT_STOPS)
        for ratio in _parse_floats(args.ratios, DEFAULT_RATIOS)
    ]

    try:
        exchange_key, resolved = _resolve_symbols(args.exchange, symbols)
        with HistoryStore(args.db_path) as store:

            def provider(symbol: str):
                return (
                    _load(store, exchange_key, symbol, simulator_settings.primary_timeframe, simulator_settings.row_limit),
                    _load(store, exchange_key, symbol, simulator_settings.daily_timeframe, simulator_settings.row_limit),
                    _load(store, exchange_key, symbol, simulator_settings.entry_timeframe, simulator_settings.row_limit),
                )

            report = run_walk_forward(
                provider,
                exchange=exchange_key,
                symbols=resolved,
                settings=settings,
                simulator_settings=simulator_settings,
                grid=grid,
                folds=max(2, args.folds),
                test_days=max(3, args.test_days),
                train_days=max(14, args.train_days),
                min_train_trades=max(1, args.min_train_trades),
            )
        print(format_walk_forward_report(report))
        return 0
    except (HistoryStoreError, WalkForwardError, ValueError) as exc:
        print(f"Walk-forward evaluation failed: {exc}", file=sys.stderr)
        return 1


def _window_stats(
    trades: Sequence[SimulatedTrade],
    start: datetime,
    end: datetime,
) -> WindowStats:
    selected = [
        trade
        for trade in trades
        if start <= trade.entry_time < end and trade.outcome != "OPEN"
    ]
    wins = sum(1 for trade in selected if trade.outcome == "TP")
    net_r_values = [trade.net_r for trade in selected if trade.net_r is not None]
    return WindowStats(
        trades=len(selected),
        wins=wins,
        win_rate=wins / len(selected) if selected else None,
        net_r=sum(net_r_values) / len(net_r_values) if net_r_values else None,
        net_pnl=sum(trade.net_pnl for trade in selected),
    )


def _merge_stats(windows: Sequence[WindowStats]) -> WindowStats:
    trades = sum(window.trades for window in windows)
    wins = sum(window.wins for window in windows)
    weighted_r = [
        window.net_r * window.trades
        for window in windows
        if window.net_r is not None
    ]
    r_trades = sum(
        window.trades for window in windows if window.net_r is not None
    )
    return WindowStats(
        trades=trades,
        wins=wins,
        win_rate=wins / trades if trades else None,
        net_r=sum(weighted_r) / r_trades if r_trades else None,
        net_pnl=sum(window.net_pnl for window in windows),
    )


def _stats_text(stats: WindowStats) -> str:
    win = "N/A" if stats.win_rate is None else f"{stats.win_rate:.0%}"
    net_r = "N/A" if stats.net_r is None else f"{stats.net_r:+.2f}"
    return (
        f"trades={stats.trades} win={win} netR={net_r} "
        f"netPnL=${stats.net_pnl:,.2f}"
    )


def _as_datetime(value) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)


def _parse_floats(raw: str, default: Sequence[float]) -> tuple[float, ...]:
    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return tuple(dict.fromkeys(values)) or tuple(default)


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()


if __name__ == "__main__":
    raise SystemExit(main())
