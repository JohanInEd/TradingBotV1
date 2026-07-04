from __future__ import annotations

import argparse
import json
import math
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    Evaluation,
    FuturesRecommendation,
    MarketContext,
    PaperSetup,
    ProbabilityForecast,
    TechnicalAnalysis,
)

OUTCOME_OPEN = "OPEN"
OUTCOME_TP = "TP"
OUTCOME_SL = "SL"
OUTCOME_EXPIRED = "EXPIRED"
PAPER_SETUP_LABEL = "paper setup"
PAPER_SETUP_DISCLAIMER = "paper setup only; no order placed; not financial advice"
SAME_CANDLE_RULE = (
    "Conservative public-candle rule: when TP and SL are both inside one "
    "candle after entry is observed, record SL because intrabar order is unknown."
)
ANALYSIS_GROUPS = (
    "side",
    "score_bucket",
    "market_regime",
    "volatility_regime",
    "trend_range_context",
)


@dataclass(frozen=True, slots=True)
class PaperSetupResolution:
    changed: bool
    outcome: str
    entry_reached: bool
    entry_reached_at: datetime | None
    outcome_at: datetime | None
    outcome_candle_at: datetime | None
    outcome_price: float | None
    r_multiple: float | None
    duration_hours: float | None


@dataclass(frozen=True, slots=True)
class PaperSetupStats:
    total_setups: int
    open_count: int
    tp_count: int
    sl_count: int
    expired_count: int
    win_rate: float | None
    expected_r: float | None
    average_time_to_outcome_hours: float | None


@dataclass(frozen=True, slots=True)
class PaperLedgerTrade:
    symbol: str
    side: str
    outcome: str
    entry_time: datetime | None
    exit_time: datetime | None
    entry_price: float
    exit_price: float | None
    quantity_btc: float
    notional: float
    gross_pnl: float
    fees: float
    slippage: float
    funding: float
    net_pnl: float
    gross_r: float
    net_r: float


@dataclass(frozen=True, slots=True)
class PaperLedgerStats:
    starting_equity: float
    closed_trades: int
    gross_pnl: float
    net_pnl: float
    fees: float
    slippage: float
    funding: float
    return_percent: float
    max_drawdown_percent: float
    average_net_r: float | None


@dataclass(frozen=True, slots=True)
class DriftReport:
    status: str
    detail: str
    recent_count: int
    baseline_count: int
    recent_win_rate: float | None = None
    baseline_win_rate: float | None = None
    win_rate_z: float | None = None
    recent_expected_r: float | None = None
    baseline_expected_r: float | None = None


@dataclass(frozen=True, slots=True)
class PaperSetupReport:
    total_setups: int
    overall: PaperSetupStats
    groups: dict[str, dict[str, PaperSetupStats]]
    ledger: PaperLedgerStats | None = None
    recent_trades: tuple[PaperLedgerTrade, ...] = ()
    equity_curve: tuple[dict[str, Any], ...] = ()
    drift: DriftReport | None = None


class PaperSetupJournal:
    def __init__(self, path: Path, *, horizon_hours: int = 24) -> None:
        self.path = Path(path).expanduser()
        self.horizon_hours = horizon_hours
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.initialize_schema()

    def __enter__(self) -> "PaperSetupJournal":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def initialize_schema(self) -> None:
        with self._lock:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_setups (
                    setup_key TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    closed_candle_at TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    side TEXT NOT NULL,
                    futures_action TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    reward_to_risk REAL NOT NULL,
                    close_price REAL NOT NULL,
                    technical_score REAL,
                    score_bucket TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    volatility_regime TEXT NOT NULL,
                    trend_range_context TEXT NOT NULL,
                    quantity_btc REAL NOT NULL,
                    notional REAL NOT NULL,
                    max_loss REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    signal_json TEXT NOT NULL,
                    market_context_json TEXT,
                    probability_forecast_json TEXT,
                    setup_json TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'OPEN',
                    entry_reached INTEGER NOT NULL DEFAULT 0,
                    entry_reached_at TEXT,
                    outcome_at TEXT,
                    outcome_candle_at TEXT,
                    outcome_price REAL,
                    r_multiple REAL,
                    duration_hours REAL,
                    expires_at TEXT NOT NULL,
                    same_candle_rule TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (
                        exchange,
                        symbol,
                        timeframe,
                        closed_candle_at,
                        side,
                        entry,
                        stop_loss,
                        take_profit
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_paper_setups_open
                    ON paper_setups (exchange, symbol, timeframe, outcome, closed_candle_at);
                CREATE INDEX IF NOT EXISTS idx_paper_setups_outcome
                    ON paper_setups (outcome, closed_candle_at);
                """
            )
            self.connection.commit()

    def record(
        self,
        evaluation: Evaluation,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        settings: Settings,
    ) -> bool:
        record = build_setup_record(
            evaluation,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            settings=settings,
        )
        if record is None:
            return False
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO paper_setups (
                    setup_key,
                    exchange,
                    symbol,
                    timeframe,
                    closed_candle_at,
                    signal_time,
                    side,
                    futures_action,
                    entry,
                    stop_loss,
                    take_profit,
                    reward_to_risk,
                    close_price,
                    technical_score,
                    score_bucket,
                    market_regime,
                    volatility_regime,
                    trend_range_context,
                    quantity_btc,
                    notional,
                    max_loss,
                    leverage,
                    signal_json,
                    market_context_json,
                    probability_forecast_json,
                    setup_json,
                    outcome,
                    entry_reached,
                    expires_at,
                    same_candle_rule,
                    created_at,
                    updated_at
                )
                VALUES (
                    :setup_key,
                    :exchange,
                    :symbol,
                    :timeframe,
                    :closed_candle_at,
                    :signal_time,
                    :side,
                    :futures_action,
                    :entry,
                    :stop_loss,
                    :take_profit,
                    :reward_to_risk,
                    :close_price,
                    :technical_score,
                    :score_bucket,
                    :market_regime,
                    :volatility_regime,
                    :trend_range_context,
                    :quantity_btc,
                    :notional,
                    :max_loss,
                    :leverage,
                    :signal_json,
                    :market_context_json,
                    :probability_forecast_json,
                    :setup_json,
                    :outcome,
                    :entry_reached,
                    :expires_at,
                    :same_candle_rule,
                    :created_at,
                    :updated_at
                )
                """,
                record,
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def resolve_with_candles(
        self,
        candles: Any,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit_per_candle: int = 500,
    ) -> int:
        resolved_count = 0
        with self._lock:
            for candle in _normalise_candles(candles):
                rows = self._open_rows(
                    exchange,
                    symbol,
                    timeframe,
                    candle["time"],
                    limit=limit_per_candle,
                )
                for row in rows:
                    resolution = resolve_setup_outcome(
                        row,
                        candle,
                        horizon_hours=self.horizon_hours,
                    )
                    if not resolution.changed:
                        continue
                    self._apply_resolution(row["setup_key"], resolution)
                    if resolution.outcome != OUTCOME_OPEN:
                        resolved_count += 1
            self.connection.commit()
        return resolved_count

    def count_open(self, *, exchange: str, symbol: str, timeframe: str) -> int:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM paper_setups
                WHERE exchange = ? AND symbol = ? AND timeframe = ? AND outcome = 'OPEN'
                """,
                (exchange, symbol, timeframe),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def load_setups(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT *
                FROM paper_setups
                ORDER BY closed_candle_at ASC, side ASC
                """
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def _open_rows(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        candle_time: datetime,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM paper_setups
            WHERE exchange = ?
                AND symbol = ?
                AND timeframe = ?
                AND outcome = 'OPEN'
                AND closed_candle_at < ?
            ORDER BY closed_candle_at ASC
            LIMIT ?
            """,
            (exchange, symbol, timeframe, _iso(candle_time), max(1, limit)),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def _apply_resolution(
        self,
        setup_key: str,
        resolution: PaperSetupResolution,
    ) -> None:
        self.connection.execute(
            """
            UPDATE paper_setups
            SET outcome = ?,
                entry_reached = ?,
                entry_reached_at = ?,
                outcome_at = ?,
                outcome_candle_at = ?,
                outcome_price = ?,
                r_multiple = ?,
                duration_hours = ?,
                updated_at = ?
            WHERE setup_key = ?
            """,
            (
                resolution.outcome,
                1 if resolution.entry_reached else 0,
                _iso(resolution.entry_reached_at),
                _iso(resolution.outcome_at),
                _iso(resolution.outcome_candle_at),
                resolution.outcome_price,
                resolution.r_multiple,
                resolution.duration_hours,
                _iso(datetime.now(timezone.utc)),
                setup_key,
            ),
        )


def build_current_paper_setup(
    *,
    futures: FuturesRecommendation | None,
    technical: TechnicalAnalysis,
    evaluated_at: datetime,
    settings: Settings,
    market_context: MarketContext | None = None,
    probability_forecast: ProbabilityForecast | None = None,
) -> PaperSetup | None:
    if futures is None or futures.side not in {"LONG", "SHORT"}:
        return None
    if (
        futures.entry_price is None
        or futures.stop_loss is None
        or futures.take_profit is None
    ):
        return None
    reward_to_risk = _reward_to_risk(
        futures.entry_price,
        futures.stop_loss,
        futures.take_profit,
    )
    market_regime, volatility_regime, trend_range_context = _context_labels(
        market_context
    )
    return PaperSetup(
        label=PAPER_SETUP_LABEL,
        side=futures.side,
        action=futures.action,
        status=OUTCOME_OPEN,
        entry_price=futures.entry_price,
        stop_loss=futures.stop_loss,
        take_profit=futures.take_profit,
        reward_to_risk=reward_to_risk or settings.reward_to_risk,
        quantity_btc=futures.quantity_btc,
        notional=futures.notional,
        max_loss=futures.max_loss,
        leverage=futures.leverage,
        position_estimate=(
            f"{futures.quantity_btc:.6f} BTC / ${futures.notional:,.2f} notional"
        ),
        signal_time=evaluated_at,
        candle_time=technical.candle_time,
        close_price=technical.close,
        technical_score=technical.score,
        futures_action=futures.action,
        market_regime=market_regime,
        volatility_regime=volatility_regime,
        trend_range_context=trend_range_context,
        probability_method=(
            probability_forecast.method if probability_forecast is not None else None
        ),
        outcome=OUTCOME_OPEN,
        disclaimer=PAPER_SETUP_DISCLAIMER,
    )


def build_setup_record(
    evaluation: Evaluation,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    settings: Settings,
) -> dict[str, Any] | None:
    setup = evaluation.paper_setup or build_current_paper_setup(
        futures=evaluation.futures,
        technical=evaluation.technical,
        evaluated_at=evaluation.evaluated_at,
        settings=settings,
        market_context=evaluation.market_context,
        probability_forecast=evaluation.probability_forecast,
    )
    if setup is None:
        return None

    now = datetime.now(timezone.utc)
    expires_at = setup.candle_time + timedelta(
        hours=settings.paper_setup_horizon_hours
    )
    score_bucket = _score_bucket(setup.technical_score)
    signal_json = _json_dumps(_jsonable(evaluation.signal))
    market_context_json = _json_dumps(_jsonable(evaluation.market_context))
    probability_json = _json_dumps(_jsonable(evaluation.probability_forecast))
    setup_json = _json_dumps(_jsonable(setup))
    return {
        "setup_key": _setup_key(
            exchange,
            symbol,
            timeframe,
            setup.candle_time,
            setup.side,
            setup.entry_price,
            setup.stop_loss,
            setup.take_profit,
        ),
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "closed_candle_at": _iso(setup.candle_time),
        "signal_time": _iso(setup.signal_time),
        "side": setup.side,
        "futures_action": setup.futures_action,
        "entry": setup.entry_price,
        "stop_loss": setup.stop_loss,
        "take_profit": setup.take_profit,
        "reward_to_risk": setup.reward_to_risk,
        "close_price": setup.close_price,
        "technical_score": setup.technical_score,
        "score_bucket": score_bucket,
        "market_regime": setup.market_regime or "UNKNOWN",
        "volatility_regime": setup.volatility_regime or "UNKNOWN",
        "trend_range_context": setup.trend_range_context or "UNKNOWN",
        "quantity_btc": setup.quantity_btc,
        "notional": setup.notional,
        "max_loss": setup.max_loss,
        "leverage": setup.leverage,
        "signal_json": signal_json,
        "market_context_json": market_context_json,
        "probability_forecast_json": probability_json,
        "setup_json": setup_json,
        "outcome": OUTCOME_OPEN,
        "entry_reached": 0,
        "expires_at": _iso(expires_at),
        "same_candle_rule": SAME_CANDLE_RULE,
        "created_at": _iso(now),
        "updated_at": _iso(now),
    }


def resolve_setup_outcome(
    setup: dict[str, Any],
    candle: dict[str, Any],
    *,
    horizon_hours: int,
) -> PaperSetupResolution:
    previous_outcome = str(setup.get("outcome") or OUTCOME_OPEN)
    entry_reached = bool(setup.get("entry_reached"))
    entry_reached_at = _parse_datetime_or_none(setup.get("entry_reached_at"))
    if previous_outcome != OUTCOME_OPEN:
        return _unchanged(previous_outcome, entry_reached, entry_reached_at)

    candle_time = _parse_datetime(candle.get("time"))
    closed_at = _parse_datetime(setup.get("closed_candle_at"))
    if candle_time <= closed_at:
        return _unchanged(previous_outcome, entry_reached, entry_reached_at)

    high = _finite_or_none(candle.get("high"))
    low = _finite_or_none(candle.get("low"))
    close = _finite_or_none(candle.get("close"))
    if high is None or low is None or close is None:
        return _unchanged(previous_outcome, entry_reached, entry_reached_at)

    entry = _finite_or_none(setup.get("entry"))
    stop = _finite_or_none(setup.get("stop_loss"))
    target = _finite_or_none(setup.get("take_profit"))
    if entry is None or stop is None or target is None:
        return _unchanged(previous_outcome, entry_reached, entry_reached_at)
    side = str(setup.get("side") or "")
    reward_to_risk = _reward_to_risk(entry, stop, target)
    stop_distance = abs(entry - stop)
    if side not in {"LONG", "SHORT"} or stop_distance <= 0:
        return _unchanged(previous_outcome, entry_reached, entry_reached_at)

    changed = False
    if not entry_reached and low <= entry <= high:
        entry_reached = True
        entry_reached_at = candle_time
        changed = True

    if entry_reached:
        if side == "LONG":
            hit_stop = low <= stop
            hit_target = high >= target
        else:
            hit_stop = high >= stop
            hit_target = low <= target
        if hit_stop and hit_target:
            return _resolved(
                OUTCOME_SL,
                entry_reached,
                entry_reached_at,
                candle_time,
                closed_at,
                stop,
                -1.0,
            )
        if hit_stop:
            return _resolved(
                OUTCOME_SL,
                entry_reached,
                entry_reached_at,
                candle_time,
                closed_at,
                stop,
                -1.0,
            )
        if hit_target:
            return _resolved(
                OUTCOME_TP,
                entry_reached,
                entry_reached_at,
                candle_time,
                closed_at,
                target,
                reward_to_risk,
            )

    expires_at = _parse_datetime_or_none(setup.get("expires_at")) or (
        closed_at + timedelta(hours=horizon_hours)
    )
    if candle_time >= expires_at:
        r_multiple = (
            _expired_r_multiple(side, entry, stop, target, close)
            if entry_reached
            else 0.0
        )
        return _resolved(
            OUTCOME_EXPIRED,
            entry_reached,
            entry_reached_at,
            candle_time,
            closed_at,
            close,
            r_multiple,
        )

    return PaperSetupResolution(
        changed=changed,
        outcome=OUTCOME_OPEN,
        entry_reached=entry_reached,
        entry_reached_at=entry_reached_at,
        outcome_at=None,
        outcome_candle_at=None,
        outcome_price=None,
        r_multiple=None,
        duration_hours=None,
    )


def analyze_paper_setups(path: Path) -> PaperSetupReport:
    with PaperSetupJournal(path) as journal:
        return analyze_setup_rows(journal.load_setups(), settings=Settings())


def analyze_setup_rows(
    rows: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
) -> PaperSetupReport:
    settings = settings or Settings()
    ledger_trades = build_paper_ledger_trades(rows, settings=settings)
    groups: dict[str, dict[str, PaperSetupStats]] = {}
    for group_name in ANALYSIS_GROUPS:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(group_name) or "UNKNOWN")].append(row)
        groups[group_name] = {
            label: _stats(items) for label, items in sorted(grouped.items())
        }
    return PaperSetupReport(
        total_setups=len(rows),
        overall=_stats(rows),
        groups=groups,
        ledger=_ledger_stats(ledger_trades, settings=settings),
        recent_trades=tuple(ledger_trades[-12:]),
        equity_curve=build_portfolio_equity_curve(ledger_trades, settings=settings),
        drift=assess_performance_drift(rows),
    )


def build_portfolio_equity_curve(
    trades: list[PaperLedgerTrade],
    *,
    settings: Settings,
    limit: int = 240,
) -> tuple[dict[str, Any], ...]:
    """Replay closed paper trades across all symbols as one shared equity curve.

    Each point also reports how many other paper positions were open when the
    trade exited, which is what makes concurrent multi-symbol exposure visible.
    """
    intervals = [
        (trade.entry_time, trade.exit_time)
        for trade in trades
        if trade.entry_time is not None
    ]
    points: list[dict[str, Any]] = [
        {
            "time": None,
            "equity": settings.paper_account_equity,
            "net_pnl": 0.0,
            "outcome": "START",
            "symbol": None,
            "side": None,
            "open_positions": 0,
        }
    ]
    equity = settings.paper_account_equity
    for trade in trades:
        equity += trade.net_pnl
        exit_time = trade.exit_time or trade.entry_time
        concurrent = 0
        if exit_time is not None:
            concurrent = sum(
                1
                for entry, exit_ in intervals
                if entry is not None
                and entry <= exit_time
                and (exit_ is None or exit_ >= exit_time)
            )
        points.append(
            {
                "time": _iso(exit_time) if exit_time is not None else None,
                "equity": equity,
                "net_pnl": trade.net_pnl,
                "net_r": trade.net_r,
                "outcome": trade.outcome,
                "symbol": trade.symbol,
                "side": trade.side,
                "open_positions": concurrent,
            }
        )
    return tuple(points[-limit:])


def assess_performance_drift(
    rows: list[dict[str, Any]],
    *,
    recent_count: int = 20,
    min_baseline: int = 30,
) -> DriftReport | None:
    """Compare recent resolved-setup performance against the long-run baseline.

    Uses a one-sided binomial z-score on TP-vs-SL win rate: negative drift
    (recent worse than baseline) raises WARNING at z <= -1.5 and ALERT at
    z <= -2.5. EXPIRED outcomes are excluded because they carry no TP/SL
    information.
    """
    resolved = [
        row
        for row in rows
        if row.get("outcome") in {OUTCOME_TP, OUTCOME_SL}
    ]
    resolved.sort(key=lambda row: str(row.get("outcome_at") or ""))
    if len(resolved) < min_baseline + max(5, recent_count // 2):
        return DriftReport(
            status="INSUFFICIENT DATA",
            detail=(
                f"{len(resolved)} resolved TP/SL setups; need at least "
                f"{min_baseline + max(5, recent_count // 2)} for drift analysis."
            ),
            recent_count=len(resolved),
            baseline_count=0,
        )

    recent = resolved[-recent_count:]
    baseline = resolved[: len(resolved) - len(recent)]
    recent_wins = sum(1 for row in recent if row.get("outcome") == OUTCOME_TP)
    baseline_wins = sum(1 for row in baseline if row.get("outcome") == OUTCOME_TP)
    recent_rate = recent_wins / len(recent)
    baseline_rate = baseline_wins / len(baseline)
    variance = baseline_rate * (1.0 - baseline_rate) / len(recent)
    z_score = (
        (recent_rate - baseline_rate) / math.sqrt(variance)
        if variance > 0
        else 0.0
    )

    def _mean_r(items: list[dict[str, Any]]) -> float | None:
        values = [
            value
            for value in (_finite_or_none(row.get("r_multiple")) for row in items)
            if value is not None
        ]
        return sum(values) / len(values) if values else None

    if z_score <= -2.5:
        status = "ALERT"
        detail = (
            f"Recent win rate {recent_rate:.0%} is far below the "
            f"{baseline_rate:.0%} baseline (z={z_score:+.2f}). Live edge may "
            "have degraded; review before trusting new signals."
        )
    elif z_score <= -1.5:
        status = "WARNING"
        detail = (
            f"Recent win rate {recent_rate:.0%} is below the "
            f"{baseline_rate:.0%} baseline (z={z_score:+.2f}). Watch the next "
            "setups closely."
        )
    else:
        status = "NORMAL"
        detail = (
            f"Recent win rate {recent_rate:.0%} vs baseline "
            f"{baseline_rate:.0%} (z={z_score:+.2f}) is within expected "
            "variation."
        )
    return DriftReport(
        status=status,
        detail=detail,
        recent_count=len(recent),
        baseline_count=len(baseline),
        recent_win_rate=recent_rate,
        baseline_win_rate=baseline_rate,
        win_rate_z=z_score,
        recent_expected_r=_mean_r(recent),
        baseline_expected_r=_mean_r(baseline),
    )


def build_paper_ledger_trades(
    rows: list[dict[str, Any]],
    *,
    settings: Settings,
) -> list[PaperLedgerTrade]:
    trades: list[PaperLedgerTrade] = []
    for row in sorted(rows, key=lambda item: str(item.get("outcome_at") or "")):
        if row.get("outcome") == OUTCOME_OPEN:
            continue
        entry = _finite_or_none(row.get("entry"))
        quantity = _finite_or_none(row.get("quantity_btc")) or 0.0
        notional = _finite_or_none(row.get("notional")) or 0.0
        max_loss = _finite_or_none(row.get("max_loss")) or 0.0
        r_multiple = _finite_or_none(row.get("r_multiple"))
        if entry is None or r_multiple is None:
            continue
        exit_price = _finite_or_none(row.get("outcome_price"))
        exit_notional = quantity * exit_price if exit_price is not None else notional
        gross_pnl = r_multiple * max_loss
        fees = (notional + abs(exit_notional)) * settings.paper_ledger_fee_rate
        slippage = (
            (notional + abs(exit_notional))
            * settings.paper_ledger_slippage_bps
            / 10_000.0
        )
        duration_hours = max(0.0, _finite_or_none(row.get("duration_hours")) or 0.0)
        funding = (
            notional
            * settings.paper_ledger_funding_rate_8h
            * (duration_hours / 8.0)
            * (1.0 if row.get("side") == "LONG" else -1.0)
        )
        net_pnl = gross_pnl - fees - slippage - funding
        trades.append(
            PaperLedgerTrade(
                symbol=str(row.get("symbol") or "?"),
                side=str(row.get("side") or "UNKNOWN"),
                outcome=str(row.get("outcome") or "UNKNOWN"),
                entry_time=_parse_datetime_or_none(row.get("signal_time")),
                exit_time=_parse_datetime_or_none(row.get("outcome_candle_at"))
                or _parse_datetime_or_none(row.get("outcome_at")),
                entry_price=entry,
                exit_price=exit_price,
                quantity_btc=quantity,
                notional=notional,
                gross_pnl=gross_pnl,
                fees=fees,
                slippage=slippage,
                funding=funding,
                net_pnl=net_pnl,
                gross_r=r_multiple,
                net_r=(net_pnl / max_loss) if max_loss else 0.0,
            )
        )
    return trades


def format_paper_setup_report(report: PaperSetupReport) -> str:
    lines = [
        f"Paper setup rows: {report.total_setups}",
        _stats_line("Overall", report.overall),
        f"Same-candle rule: {SAME_CANDLE_RULE}",
    ]
    if report.ledger is not None:
        ledger = report.ledger
        lines.append(
            "Ledger: "
            f"closed={ledger.closed_trades} "
            f"gross={_usd(ledger.gross_pnl)} "
            f"net={_usd(ledger.net_pnl)} "
            f"fees={_usd(ledger.fees)} "
            f"slippage={_usd(ledger.slippage)} "
            f"funding={_usd(ledger.funding)} "
            f"return={_pct_value(ledger.return_percent)} "
            f"maxDD={_pct_value(ledger.max_drawdown_percent)} "
            f"avgNetR={_signed(ledger.average_net_r)}"
        )
    for group_name in ANALYSIS_GROUPS:
        group = report.groups.get(group_name, {})
        if not group:
            continue
        lines.append("")
        lines.append(f"By {group_name.replace('_', ' ')}:")
        for label, stats in group.items():
            lines.append(_stats_line(f"  {label}", stats))
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze BOT_PAPER_SETUP_JOURNAL_PATH paper setup outcomes"
    )
    parser.add_argument(
        "path",
        type=Path,
        help="SQLite path from BOT_PAPER_SETUP_JOURNAL_PATH",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    print(format_paper_setup_report(analyze_paper_setups(args.path)))
    return 0


def _normalise_candles(candles: Any) -> list[dict[str, Any]]:
    if candles is None:
        return []
    if isinstance(candles, dict):
        candle = _normalise_candle(candles)
        return [] if candle is None else [candle]
    if hasattr(candles, "to_dict"):
        try:
            records = candles.to_dict("records")
            return _normalise_candles(records)
        except TypeError:
            pass
    normalised: list[dict[str, Any]] = []
    for row in candles:
        candle = _normalise_candle(row)
        if candle is not None:
            normalised.append(candle)
    return sorted(normalised, key=lambda item: item["time"])


def _normalise_candle(row: Any) -> dict[str, Any] | None:
    if isinstance(row, dict):
        time_value = (
            row.get("time")
            or row.get("timestamp")
            or row.get("closed_candle_at")
        )
        high = row.get("high")
        low = row.get("low")
        close = row.get("close")
    elif isinstance(row, Sequence) and not isinstance(row, str):
        if len(row) < 5:
            return None
        time_value, _, high, low, close = row[:5]
    else:
        time_value = getattr(row, "time", None) or getattr(row, "timestamp", None)
        high = getattr(row, "high", None)
        low = getattr(row, "low", None)
        close = getattr(row, "close", None)
    try:
        candle_time = _parse_datetime(time_value)
    except (TypeError, ValueError):
        return None
    high_value = _finite_or_none(high)
    low_value = _finite_or_none(low)
    close_value = _finite_or_none(close)
    if high_value is None or low_value is None or close_value is None:
        return None
    return {
        "time": candle_time,
        "high": high_value,
        "low": low_value,
        "close": close_value,
    }


def _resolved(
    outcome: str,
    entry_reached: bool,
    entry_reached_at: datetime | None,
    candle_time: datetime,
    closed_at: datetime,
    outcome_price: float,
    r_multiple: float,
) -> PaperSetupResolution:
    return PaperSetupResolution(
        changed=True,
        outcome=outcome,
        entry_reached=entry_reached,
        entry_reached_at=entry_reached_at,
        outcome_at=datetime.now(timezone.utc),
        outcome_candle_at=candle_time,
        outcome_price=outcome_price,
        r_multiple=r_multiple,
        duration_hours=max(0.0, (candle_time - closed_at).total_seconds() / 3600.0),
    )


def _unchanged(
    outcome: str,
    entry_reached: bool,
    entry_reached_at: datetime | None,
) -> PaperSetupResolution:
    return PaperSetupResolution(
        changed=False,
        outcome=outcome,
        entry_reached=entry_reached,
        entry_reached_at=entry_reached_at,
        outcome_at=None,
        outcome_candle_at=None,
        outcome_price=None,
        r_multiple=None,
        duration_hours=None,
    )


def _expired_r_multiple(
    side: str,
    entry: float,
    stop: float,
    target: float,
    close: float,
) -> float:
    stop_distance = abs(entry - stop)
    reward_to_risk = _reward_to_risk(entry, stop, target)
    if stop_distance <= 0:
        return 0.0
    if side == "LONG":
        value = (close - entry) / stop_distance
    else:
        value = (entry - close) / stop_distance
    return max(-1.0, min(reward_to_risk, value))


def _stats(rows: list[dict[str, Any]]) -> PaperSetupStats:
    open_count = sum(1 for row in rows if row.get("outcome") == OUTCOME_OPEN)
    tp_count = sum(1 for row in rows if row.get("outcome") == OUTCOME_TP)
    sl_count = sum(1 for row in rows if row.get("outcome") == OUTCOME_SL)
    expired_count = sum(
        1 for row in rows if row.get("outcome") in {OUTCOME_EXPIRED, "CLOSED"}
    )
    closed_count = tp_count + sl_count + expired_count
    r_values: list[float] = []
    durations: list[float] = []
    for row in rows:
        if row.get("outcome") == OUTCOME_OPEN:
            continue
        r_value = _finite_or_none(row.get("r_multiple"))
        if r_value is not None:
            r_values.append(r_value)
        duration = _finite_or_none(row.get("duration_hours"))
        if duration is not None:
            durations.append(duration)
    return PaperSetupStats(
        total_setups=len(rows),
        open_count=open_count,
        tp_count=tp_count,
        sl_count=sl_count,
        expired_count=expired_count,
        win_rate=tp_count / closed_count if closed_count else None,
        expected_r=sum(r_values) / len(r_values) if r_values else None,
        average_time_to_outcome_hours=(
            sum(durations) / len(durations) if durations else None
        ),
    )


def _ledger_stats(
    trades: list[PaperLedgerTrade],
    *,
    settings: Settings,
) -> PaperLedgerStats:
    equity = settings.paper_account_equity
    peak = equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.net_pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    net_r_values = [trade.net_r for trade in trades]
    net_pnl = sum(trade.net_pnl for trade in trades)
    return PaperLedgerStats(
        starting_equity=settings.paper_account_equity,
        closed_trades=len(trades),
        gross_pnl=sum(trade.gross_pnl for trade in trades),
        net_pnl=net_pnl,
        fees=sum(trade.fees for trade in trades),
        slippage=sum(trade.slippage for trade in trades),
        funding=sum(trade.funding for trade in trades),
        return_percent=(
            net_pnl / settings.paper_account_equity * 100.0
            if settings.paper_account_equity
            else 0.0
        ),
        max_drawdown_percent=max_drawdown,
        average_net_r=(
            sum(net_r_values) / len(net_r_values) if net_r_values else None
        ),
    )


def _stats_line(label: str, stats: PaperSetupStats) -> str:
    return (
        f"{label}: total={stats.total_setups}"
        f" open={stats.open_count}"
        f" TP={stats.tp_count}"
        f" SL={stats.sl_count}"
        f" expired={stats.expired_count}"
        f" win={_pct(stats.win_rate)}"
        f" expR={_signed(stats.expected_r)}"
        f" avg_time={_hours(stats.average_time_to_outcome_hours)}"
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["entry_reached"] = bool(payload.get("entry_reached"))
    for key in ("signal_json", "market_context_json", "probability_forecast_json", "setup_json"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            try:
                payload[key.removesuffix("_json")] = json.loads(value)
            except json.JSONDecodeError:
                payload[key.removesuffix("_json")] = None
    return payload


def _setup_key(
    exchange: str,
    symbol: str,
    timeframe: str,
    candle_time: datetime,
    side: str,
    entry: float,
    stop: float,
    target: float,
) -> str:
    return "|".join(
        (
            exchange,
            symbol,
            timeframe,
            _iso(candle_time) or "",
            side,
            f"{entry:.8f}",
            f"{stop:.8f}",
            f"{target:.8f}",
        )
    )


def _context_labels(
    market_context: MarketContext | None,
) -> tuple[str | None, str | None, str | None]:
    if market_context is None:
        return None, None, None
    volatility = market_context.volatility_regime
    structure = market_context.structure_regime
    return f"{volatility} / {structure}", volatility, structure


def _reward_to_risk(entry: float, stop: float, target: float) -> float:
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0
    return abs(target - entry) / stop_distance


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.65:
        return ">= +0.65"
    if score >= 0.25:
        return "+0.25 to +0.65"
    if score > -0.25:
        return "-0.25 to +0.25"
    if score > -0.65:
        return "-0.65 to -0.25"
    return "<= -0.65"


def _parse_datetime_or_none(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime(value)


def _parse_datetime(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    number = _finite_or_none(value)
    if number is None:
        raise TypeError("Invalid datetime value")
    if number > 100_000_000_000:
        number /= 1000.0
    return datetime.fromtimestamp(number, tz=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _signed(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}"


def _hours(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f}h"


def _usd(value: float | None) -> str:
    return "N/A" if value is None else f"${value:,.2f}"


def _pct_value(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
