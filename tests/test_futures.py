from dataclasses import replace
from datetime import datetime, timezone

import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.models import MarketSnapshot, SignalResult


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        exchange="Test",
        symbol="BTC/USDT",
        price=100_000.0,
        change_24h=0.0,
        timestamp=datetime.now(timezone.utc),
        bid=99_990.0,
        ask=100_010.0,
    )


def _signal(name: str, score: float) -> SignalResult:
    return SignalResult(
        signal=name,
        raw_score=score,
        score=score,
        technical_contribution=score,
        sentiment_contribution=0.0,
        macro_contribution=0.0,
        risk_multiplier=1.0,
    )


def test_strong_buy_creates_risk_sized_long_plan() -> None:
    settings = Settings(
        paper_account_equity=10_000.0,
        risk_per_trade=0.005,
        stop_loss_percent=0.01,
        reward_to_risk=2.0,
        max_position_fraction=1.0,
    )

    result = build_futures_recommendation(
        _signal("STRONG BUY", 0.8), _market(), settings
    )

    assert result.action == "GO LONG"
    assert result.side == "LONG"
    assert result.entry_price == 100_010.0
    assert result.stop_loss == pytest.approx(99_009.9)
    assert result.take_profit == pytest.approx(102_010.2)
    assert result.max_loss == pytest.approx(50.0)


def test_strong_sell_creates_short_plan() -> None:
    settings = Settings(
        stop_loss_percent=0.01,
        reward_to_risk=2.0,
        max_position_fraction=1.0,
    )

    result = build_futures_recommendation(
        _signal("STRONG SELL", -0.8), _market(), settings
    )

    assert result.action == "GO SHORT"
    assert result.side == "SHORT"
    assert result.entry_price == 99_990.0
    assert result.stop_loss == pytest.approx(100_989.9)
    assert result.take_profit == pytest.approx(97_990.2)


def test_neutral_signal_stays_flat() -> None:
    result = build_futures_recommendation(
        _signal("HOLD / NEUTRAL", 0.2), _market(), Settings()
    )

    assert result.action == "STAY FLAT"
    assert result.side == "FLAT"
    assert result.entry_price is None
    assert result.quantity_btc == 0.0


def test_position_notional_is_capped() -> None:
    settings = replace(
        Settings(),
        paper_account_equity=1_000.0,
        risk_per_trade=0.02,
        stop_loss_percent=0.001,
        futures_leverage=1,
        max_position_fraction=0.10,
    )

    result = build_futures_recommendation(
        _signal("STRONG BUY", 0.9), _market(), settings
    )

    assert result.notional == pytest.approx(100.0)
    assert result.max_loss < 20.0
