from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import resolve_exchange_spec
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.history import HistoryStore, HistoryStoreError, normalize_candles
from btc_trading_bot.indicators import IndicatorError, analyze_multi_timeframe
from btc_trading_bot.models import (
    FuturesRecommendation,
    MacroAnalysis,
    MarketSnapshot,
    SentimentAnalysis,
    SignalResult,
    TechnicalAnalysis,
)
from btc_trading_bot.strategy import calculate_signal

OUTCOME_TP = "TP"
OUTCOME_SL = "SL"
OUTCOME_EXPIRED = "EXPIRED"
OUTCOME_LIQUIDATED = "LIQUIDATED"
OUTCOME_OPEN = "OPEN"


@dataclass(frozen=True, slots=True)
class FuturesSimulatorSettings:
    primary_timeframe: str = "1h"
    daily_timeframe: str = "1d"
    entry_timeframe: str = "1h"
    row_limit: int = 5000
    horizon_hours: int = 24
    entry_threshold: float = 0.65
    taker_fee_rate: float = 0.0004
    funding_rate_8h: float = 0.0
    maintenance_margin_rate: float = 0.005
    allow_overlap: bool = False


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    symbol: str
    side: str
    outcome: str
    entry_time: datetime
    exit_time: datetime | None
    duration_hours: float | None
    entry_price: float
    exit_price: float | None
    stop_loss: float
    take_profit: float
    liquidation_price: float | None
    liquidation_distance_percent: float | None
    liquidation_at_risk: bool
    liquidation_touched: bool
    quantity: float
    notional: float
    initial_margin: float
    max_loss: float
    leverage: int
    signal_score: float
    technical_score: float
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float
    gross_r: float | None
    net_r: float | None
    equity_after: float | None = None
    exit_index: int | None = None


@dataclass(frozen=True, slots=True)
class FuturesSimulationStats:
    total_trades: int
    open_count: int
    tp_count: int
    sl_count: int
    expired_count: int
    liquidated_count: int
    win_rate: float | None
    gross_expected_r: float | None
    net_expected_r: float | None
    total_gross_pnl: float
    total_net_pnl: float
    total_fees: float
    total_funding: float
    starting_equity: float
    ending_equity: float
    return_percent: float
    max_drawdown_percent: float
    liquidation_at_risk_count: int
    liquidation_touch_count: int
    average_duration_hours: float | None


@dataclass(frozen=True, slots=True)
class SymbolSimulation:
    symbol: str
    trades: tuple[SimulatedTrade, ...]
    stats: FuturesSimulationStats
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FuturesSimulationReport:
    exchange: str
    symbols: tuple[str, ...]
    generated_at: datetime
    settings: FuturesSimulatorSettings
    results: tuple[SymbolSimulation, ...]
    overall: FuturesSimulationStats


def simulate_futures(
    store: HistoryStore,
    *,
    exchange: str,
    symbols: Sequence[str],
    settings: Settings,
    simulator_settings: FuturesSimulatorSettings | None = None,
) -> FuturesSimulationReport:
    simulator_settings = simulator_settings or FuturesSimulatorSettings(
        primary_timeframe=settings.entry_timeframe,
        daily_timeframe=settings.daily_timeframe,
        entry_timeframe=settings.entry_timeframe,
        horizon_hours=settings.paper_setup_horizon_hours,
        entry_threshold=settings.buy_threshold,
    )
    exchange_key, resolved_symbols = _resolve_symbols(exchange, symbols)
    results = tuple(
        simulate_symbol(
            store,
            exchange=exchange_key,
            symbol=symbol,
            settings=settings,
            simulator_settings=simulator_settings,
        )
        for symbol in resolved_symbols
    )
    all_trades = sorted(
        (trade for result in results for trade in result.trades),
        key=lambda trade: trade.entry_time,
    )
    overall = _stats(
        all_trades,
        starting_equity=settings.paper_account_equity * max(1, len(resolved_symbols)),
    )
    return FuturesSimulationReport(
        exchange=exchange_key,
        symbols=tuple(resolved_symbols),
        generated_at=datetime.now(timezone.utc),
        settings=simulator_settings,
        results=results,
        overall=overall,
    )


def simulate_symbol(
    store: HistoryStore,
    *,
    exchange: str,
    symbol: str,
    settings: Settings,
    simulator_settings: FuturesSimulatorSettings,
) -> SymbolSimulation:
    try:
        primary = _load(store, exchange, symbol, simulator_settings.primary_timeframe, simulator_settings.row_limit)
        daily = _load(store, exchange, symbol, simulator_settings.daily_timeframe, simulator_settings.row_limit)
        hourly = _load(store, exchange, symbol, simulator_settings.entry_timeframe, simulator_settings.row_limit)
        _require_history(primary, daily, hourly, symbol, simulator_settings)
        trades = _simulate_symbol_trades(
            symbol,
            primary,
            daily,
            hourly,
            settings,
            simulator_settings,
        )
        stats = _stats(trades, starting_equity=settings.paper_account_equity)
        trades_with_equity = _attach_equity(trades, settings.paper_account_equity)
        return SymbolSimulation(
            symbol=symbol,
            trades=tuple(trades_with_equity),
            stats=stats,
        )
    except (HistoryStoreError, IndicatorError, ValueError) as exc:
        empty_stats = _stats((), starting_equity=settings.paper_account_equity)
        return SymbolSimulation(
            symbol=symbol,
            trades=(),
            stats=empty_stats,
            error=str(exc),
        )


def format_simulation_report(report: FuturesSimulationReport) -> str:
    lines = [
        f"Futures simulator: {report.exchange}",
        (
            "Mode: candle-only technical replay with completed "
            f"{report.settings.primary_timeframe}/"
            f"{report.settings.daily_timeframe}/"
            f"{report.settings.entry_timeframe} confirmation"
        ),
        (
            f"Costs: taker_fee={report.settings.taker_fee_rate:.4%} "
            f"funding_8h={report.settings.funding_rate_8h:.4%} "
            f"maintenance_margin={report.settings.maintenance_margin_rate:.2%}"
        ),
        _stats_line("Overall", report.overall),
    ]
    for result in report.results:
        lines.append("")
        if result.error:
            lines.append(f"{result.symbol}: unavailable - {result.error}")
            continue
        lines.append(_stats_line(result.symbol, result.stats))
        last_trades = result.trades[-3:]
        for trade in last_trades:
            lines.append(
                "  "
                f"{trade.entry_time.isoformat()} {trade.side} {trade.outcome} "
                f"entry={trade.entry_price:.6g} exit={_price(trade.exit_price)} "
                f"netR={_signed(trade.net_r)} netPnL={_money(trade.net_pnl)} "
                f"liq_dist={_pct(trade.liquidation_distance_percent)}"
            )
    lines.append("")
    lines.append(
        "Public-candle simulator only; same-candle path order is conservative "
        "and this does not place orders."
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(
        description="Replay local public candles as paper futures long/short contracts"
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
        help="Explicit exchange, e.g. binance-usdm",
    )
    parser.add_argument(
        "--symbols",
        default=os.getenv("BOT_SYMBOLS") or os.getenv("BOT_SYMBOL", "BTC/USDT"),
        help="Comma-separated symbols to simulate",
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument(
        "--primary-timeframe",
        default=settings.entry_timeframe,
        help="Primary candle timeframe to trade, defaults to the 1h entry timeframe",
    )
    parser.add_argument(
        "--daily-timeframe",
        default=settings.daily_timeframe,
        help="Higher-timeframe trend confirmation candle, defaults to 1d",
    )
    parser.add_argument(
        "--entry-timeframe",
        default=settings.entry_timeframe,
        help="Entry timing candle, defaults to 1h",
    )
    parser.add_argument("--horizon-hours", type=int, default=settings.paper_setup_horizon_hours)
    parser.add_argument("--entry-threshold", type=float, default=settings.buy_threshold)
    parser.add_argument("--fee-rate", type=float, default=0.0004)
    parser.add_argument("--funding-rate-8h", type=float, default=0.0)
    parser.add_argument("--maintenance-margin-rate", type=float, default=0.005)
    parser.add_argument("--leverage", type=int, default=settings.futures_leverage)
    parser.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Allow a new paper contract before the prior symbol contract resolves",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.db_path is None:
        print("Set BOT_HISTORY_DB_PATH or pass --db-path.", file=sys.stderr)
        return 2
    symbols = _parse_symbols(args.symbols)
    if not symbols:
        print("At least one symbol is required.", file=sys.stderr)
        return 2
    settings = replace(Settings.from_env(), futures_leverage=max(1, args.leverage))
    simulator_settings = FuturesSimulatorSettings(
        primary_timeframe=args.primary_timeframe,
        daily_timeframe=args.daily_timeframe,
        entry_timeframe=args.entry_timeframe,
        row_limit=max(80, args.limit),
        horizon_hours=max(1, args.horizon_hours),
        entry_threshold=max(0.0, min(1.0, args.entry_threshold)),
        taker_fee_rate=max(0.0, args.fee_rate),
        funding_rate_8h=args.funding_rate_8h,
        maintenance_margin_rate=max(0.0, args.maintenance_margin_rate),
        allow_overlap=args.allow_overlap,
    )
    try:
        with HistoryStore(args.db_path) as store:
            report = simulate_futures(
                store,
                exchange=args.exchange,
                symbols=symbols,
                settings=settings,
                simulator_settings=simulator_settings,
            )
        print(format_simulation_report(report))
        return 0
    except (HistoryStoreError, ValueError) as exc:
        print(f"Futures simulation failed: {exc}", file=sys.stderr)
        return 1


def _simulate_symbol_trades(
    symbol: str,
    primary: pd.DataFrame,
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    settings: Settings,
    simulator_settings: FuturesSimulatorSettings,
) -> tuple[SimulatedTrade, ...]:
    signal_settings = replace(
        settings,
        technical_weight=1.0,
        sentiment_weight=0.0,
        macro_weight=0.0,
        buy_threshold=simulator_settings.entry_threshold,
        sell_threshold=-simulator_settings.entry_threshold,
        paper_setup_horizon_hours=simulator_settings.horizon_hours,
    )
    sentiment = SentimentAnalysis(score=0.0, label="Neutral")
    macro = MacroAnalysis(score=0.0, status="NO HISTORICAL MACRO", risk_multiplier=1.0)

    trades: list[SimulatedTrade] = []
    index = 59
    while index < len(primary) - 1:
        current_time = _as_datetime(primary.iloc[index]["timestamp"])
        daily_window = _until(daily, current_time)
        hourly_window = _until(hourly, current_time)
        if len(daily_window) < 60 or len(hourly_window) < 60:
            index += 1
            continue
        primary_window = primary.iloc[: index + 1]
        try:
            technical = analyze_multi_timeframe(
                primary_window,
                daily_window,
                hourly_window,
                primary_weight=settings.primary_timeframe_weight,
                daily_weight=settings.daily_timeframe_weight,
                hourly_weight=settings.entry_timeframe_weight,
            )
        except IndicatorError:
            index += 1
            continue

        signal = calculate_signal(technical, sentiment, macro, signal_settings)
        market = MarketSnapshot(
            exchange="simulator",
            symbol=symbol,
            price=technical.close,
            change_24h=None,
            timestamp=current_time,
            bid=technical.close,
            ask=technical.close,
            source="HISTORY",
        )
        futures = build_futures_recommendation(signal, market, signal_settings)
        if futures.side in {"LONG", "SHORT"}:
            trade = _simulate_trade(
                symbol,
                primary,
                index,
                futures,
                technical,
                signal,
                simulator_settings,
            )
            trades.append(trade)
            if not simulator_settings.allow_overlap and trade.exit_index is not None:
                index = max(index + 1, trade.exit_index)
                continue
        index += 1
    return tuple(trades)


def _simulate_trade(
    symbol: str,
    primary: pd.DataFrame,
    entry_index: int,
    futures: FuturesRecommendation,
    technical: TechnicalAnalysis,
    signal: SignalResult,
    simulator_settings: FuturesSimulatorSettings,
) -> SimulatedTrade:
    if futures.entry_price is None or futures.stop_loss is None or futures.take_profit is None:
        raise ValueError("Futures recommendation is missing paper prices")
    entry = futures.entry_price
    stop = futures.stop_loss
    target = futures.take_profit
    side = futures.side
    entry_time = _as_datetime(primary.iloc[entry_index]["timestamp"])
    deadline = entry_time + timedelta(hours=simulator_settings.horizon_hours)
    liquidation_price = _liquidation_price(
        side,
        entry,
        futures.leverage,
        simulator_settings.maintenance_margin_rate,
    )
    liquidation_distance = _liquidation_distance_percent(side, entry, liquidation_price)
    liquidation_at_risk = _liquidation_inside_stop(side, liquidation_price, stop)

    outcome = OUTCOME_OPEN
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_index: int | None = None
    liquidation_touched = False

    for index in range(entry_index + 1, len(primary)):
        row = primary.iloc[index]
        candle_time = _as_datetime(row["timestamp"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        hit_liquidation = _hit_liquidation(side, liquidation_price, high, low)
        liquidation_touched = liquidation_touched or hit_liquidation
        hit_stop, hit_target = _hit_exit(side, stop, target, high, low)

        if hit_liquidation and liquidation_at_risk:
            outcome = OUTCOME_LIQUIDATED
            exit_price = liquidation_price
        elif hit_stop:
            outcome = OUTCOME_SL
            exit_price = stop
        elif hit_target:
            outcome = OUTCOME_TP
            exit_price = target
        elif candle_time >= deadline:
            outcome = OUTCOME_EXPIRED
            exit_price = close

        if exit_price is not None:
            exit_time = candle_time
            exit_index = index
            break

    duration_hours = (
        None if exit_time is None else max(0.0, (exit_time - entry_time).total_seconds() / 3600.0)
    )
    gross_pnl = _gross_pnl(side, entry, exit_price, futures.quantity_btc)
    exit_notional = futures.quantity_btc * (exit_price if exit_price is not None else entry)
    fees = (futures.notional + exit_notional) * simulator_settings.taker_fee_rate
    funding = _funding_cost(
        side,
        futures.notional,
        duration_hours,
        simulator_settings.funding_rate_8h,
    )
    net_pnl = gross_pnl - fees - funding
    max_loss = futures.max_loss
    gross_r = gross_pnl / max_loss if max_loss > 0 and outcome != OUTCOME_OPEN else None
    net_r = net_pnl / max_loss if max_loss > 0 and outcome != OUTCOME_OPEN else None
    initial_margin = futures.notional / max(1, futures.leverage)

    return SimulatedTrade(
        symbol=symbol,
        side=side,
        outcome=outcome,
        entry_time=entry_time,
        exit_time=exit_time,
        duration_hours=duration_hours,
        entry_price=entry,
        exit_price=exit_price,
        stop_loss=stop,
        take_profit=target,
        liquidation_price=liquidation_price,
        liquidation_distance_percent=liquidation_distance,
        liquidation_at_risk=liquidation_at_risk,
        liquidation_touched=liquidation_touched,
        quantity=futures.quantity_btc,
        notional=futures.notional,
        initial_margin=initial_margin,
        max_loss=max_loss,
        leverage=futures.leverage,
        signal_score=signal.score,
        technical_score=technical.score,
        gross_pnl=gross_pnl,
        fees=fees,
        funding=funding,
        net_pnl=net_pnl,
        gross_r=gross_r,
        net_r=net_r,
        exit_index=exit_index,
    )


def _stats(
    trades: Sequence[SimulatedTrade],
    *,
    starting_equity: float,
) -> FuturesSimulationStats:
    closed = [trade for trade in trades if trade.outcome != OUTCOME_OPEN]
    tp_count = sum(1 for trade in trades if trade.outcome == OUTCOME_TP)
    sl_count = sum(1 for trade in trades if trade.outcome == OUTCOME_SL)
    expired_count = sum(1 for trade in trades if trade.outcome == OUTCOME_EXPIRED)
    liquidated_count = sum(1 for trade in trades if trade.outcome == OUTCOME_LIQUIDATED)
    equity = starting_equity
    peak = starting_equity
    max_drawdown = 0.0
    for trade in trades:
        if trade.outcome == OUTCOME_OPEN:
            continue
        equity += trade.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    durations = [
        trade.duration_hours
        for trade in closed
        if trade.duration_hours is not None and math.isfinite(trade.duration_hours)
    ]
    gross_r_values = [trade.gross_r for trade in closed if trade.gross_r is not None]
    net_r_values = [trade.net_r for trade in closed if trade.net_r is not None]
    return FuturesSimulationStats(
        total_trades=len(trades),
        open_count=sum(1 for trade in trades if trade.outcome == OUTCOME_OPEN),
        tp_count=tp_count,
        sl_count=sl_count,
        expired_count=expired_count,
        liquidated_count=liquidated_count,
        win_rate=tp_count / len(closed) if closed else None,
        gross_expected_r=_mean(gross_r_values),
        net_expected_r=_mean(net_r_values),
        total_gross_pnl=sum(trade.gross_pnl for trade in closed),
        total_net_pnl=sum(trade.net_pnl for trade in closed),
        total_fees=sum(trade.fees for trade in closed),
        total_funding=sum(trade.funding for trade in closed),
        starting_equity=starting_equity,
        ending_equity=equity,
        return_percent=((equity / starting_equity) - 1.0) * 100.0 if starting_equity > 0 else 0.0,
        max_drawdown_percent=max_drawdown * 100.0,
        liquidation_at_risk_count=sum(1 for trade in trades if trade.liquidation_at_risk),
        liquidation_touch_count=sum(1 for trade in trades if trade.liquidation_touched),
        average_duration_hours=_mean(durations),
    )


def _attach_equity(
    trades: Sequence[SimulatedTrade],
    starting_equity: float,
) -> tuple[SimulatedTrade, ...]:
    equity = starting_equity
    updated: list[SimulatedTrade] = []
    for trade in trades:
        if trade.outcome != OUTCOME_OPEN:
            equity += trade.net_pnl
        updated.append(replace(trade, equity_after=equity))
    return tuple(updated)


def _load(
    store: HistoryStore,
    exchange: str,
    symbol: str,
    timeframe: str,
    limit: int,
) -> pd.DataFrame:
    return normalize_candles(
        store.load_candles(exchange, symbol, timeframe, limit=max(1, limit))
    )


def _require_history(
    primary: pd.DataFrame,
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    symbol: str,
    simulator_settings: FuturesSimulatorSettings,
) -> None:
    missing: list[str] = []
    if len(primary) < 61:
        missing.append(simulator_settings.primary_timeframe)
    if len(daily) < 60:
        missing.append(simulator_settings.daily_timeframe)
    if len(hourly) < 60:
        missing.append(simulator_settings.entry_timeframe)
    if missing:
        missing = list(dict.fromkeys(missing))
        raise HistoryStoreError(
            f"{symbol} needs at least 60 candles for: {', '.join(missing)}"
        )


def _until(frame: pd.DataFrame, timestamp: datetime) -> pd.DataFrame:
    times = pd.to_datetime(frame["timestamp"], utc=True)
    cutoff = pd.Timestamp(timestamp).tz_convert(timezone.utc)
    return frame.loc[times <= cutoff].reset_index(drop=True)


def _resolve_symbols(exchange: str, symbols: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    if exchange == "auto":
        raise ValueError("Choose an explicit exchange for futures simulation")
    resolved: list[str] = []
    seen: set[str] = set()
    exchange_key: str | None = None
    for symbol in symbols:
        spec = resolve_exchange_spec(exchange, symbol.upper())
        exchange_key = spec.ccxt_id if exchange_key is None else exchange_key
        if spec.symbol in seen:
            continue
        resolved.append(spec.symbol)
        seen.add(spec.symbol)
    return exchange_key or exchange, tuple(resolved)


def _parse_symbols(value: str) -> tuple[str, ...]:
    symbols: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        symbol = part.strip().upper()
        if symbol and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return tuple(symbols)


def _hit_exit(side: str, stop: float, target: float, high: float, low: float) -> tuple[bool, bool]:
    if side == "LONG":
        return low <= stop, high >= target
    return high >= stop, low <= target


def _hit_liquidation(side: str, liquidation_price: float | None, high: float, low: float) -> bool:
    if liquidation_price is None:
        return False
    if side == "LONG":
        return low <= liquidation_price
    return high >= liquidation_price


def _liquidation_price(
    side: str,
    entry: float,
    leverage: int,
    maintenance_margin_rate: float,
) -> float | None:
    if entry <= 0 or leverage <= 0:
        return None
    margin_fraction = 1.0 / leverage
    if side == "LONG":
        return max(0.0, entry * (1.0 - margin_fraction + maintenance_margin_rate))
    return entry * (1.0 + margin_fraction - maintenance_margin_rate)


def _liquidation_distance_percent(
    side: str,
    entry: float,
    liquidation_price: float | None,
) -> float | None:
    if liquidation_price is None or entry <= 0:
        return None
    if side == "LONG":
        return max(0.0, (entry - liquidation_price) / entry * 100.0)
    return max(0.0, (liquidation_price - entry) / entry * 100.0)


def _liquidation_inside_stop(side: str, liquidation_price: float | None, stop: float) -> bool:
    if liquidation_price is None:
        return False
    if side == "LONG":
        return liquidation_price >= stop
    return liquidation_price <= stop


def _gross_pnl(side: str, entry: float, exit_price: float | None, quantity: float) -> float:
    if exit_price is None:
        return 0.0
    if side == "LONG":
        return (exit_price - entry) * quantity
    return (entry - exit_price) * quantity


def _funding_cost(
    side: str,
    notional: float,
    duration_hours: float | None,
    funding_rate_8h: float,
) -> float:
    if duration_hours is None or duration_hours <= 0:
        return 0.0
    direction = 1.0 if side == "LONG" else -1.0
    return notional * funding_rate_8h * (duration_hours / 8.0) * direction


def _as_datetime(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    parsed = pd.to_datetime(value, utc=True)
    return parsed.to_pydatetime()


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()


def _mean(values: Sequence[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _stats_line(label: str, stats: FuturesSimulationStats) -> str:
    return (
        f"{label}: trades={stats.total_trades}"
        f" open={stats.open_count}"
        f" TP={stats.tp_count}"
        f" SL={stats.sl_count}"
        f" expired={stats.expired_count}"
        f" liq={stats.liquidated_count}"
        f" win={_pct_ratio(stats.win_rate)}"
        f" netR={_signed(stats.net_expected_r)}"
        f" pnl={_money(stats.total_net_pnl)}"
        f" fees={_money(stats.total_fees)}"
        f" funding={_money(stats.total_funding)}"
        f" return={stats.return_percent:+.2f}%"
        f" maxDD={stats.max_drawdown_percent:.2f}%"
        f" liqRisk={stats.liquidation_at_risk_count}"
        f" liqTouch={stats.liquidation_touch_count}"
    )


def _price(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.6g}"


def _money(value: float | None) -> str:
    return "N/A" if value is None else f"${value:,.2f}"


def _signed(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}"


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _pct_ratio(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
