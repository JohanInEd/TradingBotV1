from datetime import datetime, timedelta, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.portfolio import (
    build_portfolio_state,
    check_portfolio_entry,
    empty_portfolio_state,
    register_open_position,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _open_row(symbol: str, side: str = "LONG", max_loss: float = 50.0, candle: str = "2026-07-01T08:00:00+00:00") -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "outcome": "OPEN",
        "max_loss": max_loss,
        "closed_candle_at": candle,
    }


def _closed_row(
    symbol: str,
    outcome: str,
    *,
    r_multiple: float,
    outcome_at: datetime,
    max_loss: float = 50.0,
) -> dict:
    return {
        "symbol": symbol,
        "side": "LONG",
        "outcome": outcome,
        "entry": 100.0,
        "quantity_btc": 1.0,
        "notional": 100.0,
        "max_loss": max_loss,
        "r_multiple": r_multiple,
        "outcome_price": 100.0 + r_multiple,
        "outcome_at": outcome_at.isoformat(),
        "signal_time": outcome_at.isoformat(),
        "duration_hours": 4.0,
        "closed_candle_at": "2026-06-30T08:00:00+00:00",
    }


def test_state_counts_open_positions_risk_and_cooldowns() -> None:
    settings = Settings(portfolio_symbol_cooldown_hours=8.0)
    rows = [
        _open_row("BTC/USDT:USDT", "LONG", 40.0),
        _open_row("ETH/USDT:USDT", "SHORT", 35.0),
        _closed_row(
            "SOL/USDT:USDT",
            "SL",
            r_multiple=-1.0,
            outcome_at=NOW - timedelta(hours=2),
        ),
    ]

    state = build_portfolio_state(rows, settings=settings, now=NOW)

    assert state.open_positions == 2
    assert state.long_positions == 1
    assert state.short_positions == 1
    assert state.open_risk_usd == 75.0
    assert state.open_symbols == ("BTC/USDT:USDT", "ETH/USDT:USDT")
    assert ("BTC/USDT:USDT", "LONG", "2026-07-01T08:00:00+00:00") in state.open_setup_keys
    cooldown_symbols = [symbol for symbol, _ in state.cooldowns]
    assert cooldown_symbols == ["SOL/USDT:USDT"]
    assert not state.kill_switch_active


def test_kill_switch_activates_on_drawdown() -> None:
    settings = Settings(
        paper_account_equity=1000.0,
        portfolio_max_drawdown_percent=10.0,
    )
    rows = [
        _closed_row(
            "BTC/USDT:USDT",
            "SL",
            r_multiple=-1.0,
            max_loss=150.0,
            outcome_at=NOW - timedelta(days=2),
        ),
    ]

    state = build_portfolio_state(rows, settings=settings, now=NOW)

    assert state.current_drawdown_percent > 10.0
    assert state.kill_switch_active
    decision = check_portfolio_entry(
        state,
        symbol="ETH/USDT:USDT",
        side="LONG",
        max_loss=10.0,
        settings=settings,
        now=NOW,
    )
    assert not decision.allowed
    assert any("kill switch" in reason.lower() for reason in decision.reasons)


def test_entry_limits_max_positions_direction_risk_and_cooldown() -> None:
    settings = Settings(
        paper_account_equity=10_000.0,
        portfolio_max_open_positions=2,
        portfolio_max_same_direction=1,
        portfolio_max_open_risk_fraction=0.01,
        portfolio_symbol_cooldown_hours=8.0,
    )
    rows = [
        _open_row("BTC/USDT:USDT", "LONG", 60.0),
        _closed_row(
            "SOL/USDT:USDT",
            "SL",
            r_multiple=-1.0,
            outcome_at=NOW - timedelta(hours=1),
        ),
    ]
    state = build_portfolio_state(rows, settings=settings, now=NOW)

    same_direction = check_portfolio_entry(
        state, symbol="ETH/USDT:USDT", side="LONG", max_loss=10.0,
        settings=settings, now=NOW,
    )
    assert not same_direction.allowed
    assert any("same-direction" in reason.lower() for reason in same_direction.reasons)

    over_budget = check_portfolio_entry(
        state, symbol="ETH/USDT:USDT", side="SHORT", max_loss=90.0,
        settings=settings, now=NOW,
    )
    assert not over_budget.allowed
    assert any("open-risk budget" in reason.lower() for reason in over_budget.reasons)

    cooled_down = check_portfolio_entry(
        state, symbol="SOL/USDT:USDT", side="SHORT", max_loss=5.0,
        settings=settings, now=NOW,
    )
    assert not cooled_down.allowed
    assert any("cooldown" in reason.lower() for reason in cooled_down.reasons)

    allowed = check_portfolio_entry(
        state, symbol="ETH/USDT:USDT", side="SHORT", max_loss=5.0,
        settings=settings, now=NOW,
    )
    assert allowed.allowed
    assert allowed.status == "ALLOWED"

    # A second position makes max-open the binding limit.
    fuller = register_open_position(
        state, symbol="ETH/USDT:USDT", side="SHORT", max_loss=5.0
    )
    third = check_portfolio_entry(
        fuller, symbol="XRP/USDT:USDT", side="SHORT", max_loss=5.0,
        settings=settings, now=NOW,
    )
    assert not third.allowed
    assert any("max concurrent" in reason.lower() for reason in third.reasons)


def test_tracked_setup_is_idempotent() -> None:
    settings = Settings(portfolio_max_open_positions=1)
    candle = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    rows = [_open_row("BTC/USDT:USDT", "LONG", 40.0, candle.isoformat())]
    state = build_portfolio_state(rows, settings=settings, now=NOW)

    decision = check_portfolio_entry(
        state,
        symbol="BTC/USDT:USDT",
        side="LONG",
        max_loss=40.0,
        settings=settings,
        now=NOW,
        candle_time=candle,
    )

    assert decision.allowed
    assert decision.status == "TRACKED"


def test_disabled_portfolio_allows_everything() -> None:
    settings = Settings(portfolio_risk_enabled=False, portfolio_max_open_positions=1)
    state = register_open_position(
        empty_portfolio_state(settings, NOW),
        symbol="BTC/USDT:USDT",
        side="LONG",
        max_loss=999.0,
    )

    decision = check_portfolio_entry(
        state, symbol="ETH/USDT:USDT", side="LONG", max_loss=999.0,
        settings=settings, now=NOW,
    )

    assert decision.allowed
    assert decision.status == "DISABLED"
