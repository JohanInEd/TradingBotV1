from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.models import PortfolioDecision, PortfolioState
from btc_trading_bot.paper_setups import (
    OUTCOME_OPEN,
    OUTCOME_SL,
    build_paper_ledger_trades,
)


def build_portfolio_state(
    rows: list[dict[str, Any]],
    *,
    settings: Settings,
    now: datetime | None = None,
) -> PortfolioState:
    """Summarize journal rows into shared portfolio exposure and risk state.

    All scanned crypto symbols are treated as one correlated group: the
    same-direction cap and shared risk budget exist because simultaneous
    longs on highly correlated assets behave like one oversized position.
    """
    now = now or datetime.now(timezone.utc)
    open_rows = [row for row in rows if row.get("outcome") == OUTCOME_OPEN]
    long_positions = sum(1 for row in open_rows if row.get("side") == "LONG")
    short_positions = sum(1 for row in open_rows if row.get("side") == "SHORT")
    open_risk = sum(_finite(row.get("max_loss")) for row in open_rows)
    open_symbols = tuple(
        dict.fromkeys(str(row.get("symbol") or "?") for row in open_rows)
    )
    open_setup_keys = tuple(
        dict.fromkeys(
            (
                str(row.get("symbol") or "?"),
                str(row.get("side") or "?"),
                str(row.get("closed_candle_at") or ""),
            )
            for row in open_rows
        )
    )

    equity = settings.paper_account_equity
    peak = equity
    for trade in build_paper_ledger_trades(rows, settings=settings):
        equity += trade.net_pnl
        peak = max(peak, equity)
    drawdown_percent = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0

    cooldown_hours = settings.portfolio_symbol_cooldown_hours
    cooldowns: dict[str, datetime] = {}
    if cooldown_hours > 0:
        for row in rows:
            if row.get("outcome") != OUTCOME_SL:
                continue
            outcome_at = _parse_datetime(row.get("outcome_at"))
            if outcome_at is None:
                continue
            until = outcome_at + timedelta(hours=cooldown_hours)
            if until <= now:
                continue
            symbol = str(row.get("symbol") or "?")
            existing = cooldowns.get(symbol)
            if existing is None or until > existing:
                cooldowns[symbol] = until

    return PortfolioState(
        open_positions=len(open_rows),
        long_positions=long_positions,
        short_positions=short_positions,
        open_risk_usd=open_risk,
        equity=equity,
        peak_equity=peak,
        current_drawdown_percent=drawdown_percent,
        kill_switch_active=(
            drawdown_percent >= settings.portfolio_max_drawdown_percent
        ),
        generated_at=now,
        open_symbols=open_symbols,
        cooldowns=tuple(sorted(cooldowns.items())),
        open_setup_keys=open_setup_keys,
    )


def empty_portfolio_state(
    settings: Settings, now: datetime | None = None
) -> PortfolioState:
    return build_portfolio_state([], settings=settings, now=now)


def check_portfolio_entry(
    state: PortfolioState,
    *,
    symbol: str,
    side: str,
    max_loss: float,
    settings: Settings,
    now: datetime | None = None,
    candle_time: datetime | None = None,
) -> PortfolioDecision:
    if not settings.portfolio_risk_enabled:
        return PortfolioDecision(
            allowed=True,
            status="DISABLED",
            reasons=("Portfolio risk limits are disabled.",),
            state=state,
        )
    now = now or datetime.now(timezone.utc)

    if candle_time is not None:
        key = (symbol, side, _iso(candle_time))
        if key in state.open_setup_keys:
            # This exact closed-candle setup is already the tracked open
            # position, so re-evaluating it must not consume new budget.
            return PortfolioDecision(
                allowed=True,
                status="TRACKED",
                reasons=(
                    f"{symbol} {side} setup from this closed candle is "
                    "already tracked as the open paper position.",
                ),
                state=state,
            )

    reasons: list[str] = []

    if state.kill_switch_active:
        reasons.append(
            "Portfolio kill switch is active: current drawdown "
            f"{state.current_drawdown_percent:.1f}% >= "
            f"{settings.portfolio_max_drawdown_percent:.1f}%."
        )
    if state.open_positions >= settings.portfolio_max_open_positions:
        reasons.append(
            "Max concurrent paper positions reached "
            f"({state.open_positions}/{settings.portfolio_max_open_positions})."
        )
    if symbol in state.open_symbols:
        reasons.append(f"{symbol} already has an open paper setup.")

    same_direction = (
        state.long_positions if side == "LONG" else state.short_positions
    )
    if same_direction >= settings.portfolio_max_same_direction:
        reasons.append(
            f"Correlated same-direction cap reached: {same_direction} open "
            f"{side} position(s) >= {settings.portfolio_max_same_direction}."
        )

    risk_budget = state.equity * settings.portfolio_max_open_risk_fraction
    if max_loss > 0 and state.open_risk_usd + max_loss > risk_budget:
        reasons.append(
            "Shared open-risk budget exhausted: "
            f"${state.open_risk_usd + max_loss:,.0f} planned vs "
            f"${risk_budget:,.0f} allowed "
            f"({settings.portfolio_max_open_risk_fraction:.1%} of equity)."
        )

    cooldown_until = next(
        (until for cooldown_symbol, until in state.cooldowns
         if cooldown_symbol == symbol),
        None,
    )
    if cooldown_until is not None and cooldown_until > now:
        reasons.append(
            f"{symbol} is in post-stop-loss cooldown until "
            f"{cooldown_until.strftime('%Y-%m-%d %H:%M UTC')}."
        )

    if reasons:
        return PortfolioDecision(
            allowed=False, status="BLOCKED", reasons=tuple(reasons), state=state
        )
    return PortfolioDecision(
        allowed=True,
        status="ALLOWED",
        reasons=("Portfolio limits allow this paper setup.",),
        state=state,
    )


def register_open_position(
    state: PortfolioState,
    *,
    symbol: str,
    side: str,
    max_loss: float,
) -> PortfolioState:
    """Return state as if the candidate were opened (greedy scanner allocation)."""
    return replace(
        state,
        open_positions=state.open_positions + 1,
        long_positions=state.long_positions + (1 if side == "LONG" else 0),
        short_positions=state.short_positions + (1 if side == "SHORT" else 0),
        open_risk_usd=state.open_risk_usd + max(0.0, max_loss),
        open_symbols=(
            state.open_symbols
            if symbol in state.open_symbols
            else (*state.open_symbols, symbol)
        ),
    )


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
