from __future__ import annotations

from datetime import datetime, timezone

import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    FuturesMetrics,
    FuturesRecommendation,
    MarketContext,
    ProbabilityForecast,
)
from btc_trading_bot.risk_filters import apply_do_not_trade_filters


def _long_plan() -> FuturesRecommendation:
    return FuturesRecommendation(
        action="GO LONG",
        side="LONG",
        confidence=0.8,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        quantity_btc=0.1,
        notional=10.0,
        max_loss=1.0,
        leverage=1,
        reason="test",
    )


def _probability(**overrides) -> ProbabilityForecast:
    payload = {
        "horizon_hours": 24,
        "up_probability": 0.58,
        "down_probability": 0.35,
        "flat_probability": 0.07,
        "long_tp_before_sl_probability": 0.56,
        "long_sl_before_tp_probability": 0.32,
        "short_tp_before_sl_probability": 0.30,
        "short_sl_before_tp_probability": 0.54,
        "expected_long_r": 0.28,
        "expected_short_r": -0.22,
        "average_forward_return_percent": 1.4,
        "sample_size": 80,
        "candidate_count": 140,
        "confidence": "MEDIUM",
        "method": "test",
        "generated_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return ProbabilityForecast(**payload)


def _context(**overrides) -> MarketContext:
    payload = {
        "volatility_regime": "NORMAL VOLATILITY",
        "structure_regime": "TRENDING UP",
        "atr_percent": 1.2,
        "realized_volatility_percent": 1.1,
        "bollinger_width_percent": 4.0,
        "range_position_percent": 72.0,
        "trend_strength_percent": 2.5,
        "reason": "test",
        "updated_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    return MarketContext(**payload)


def test_do_not_trade_filters_pass_constructive_long_context() -> None:
    futures, result = apply_do_not_trade_filters(
        _long_plan(),
        Settings(),
        probability_forecast=_probability(),
        market_context=_context(),
        futures_metrics=FuturesMetrics(
            mark_price=100.0,
            index_price=100.0,
            funding_rate=0.0001,
            next_funding_at=None,
            open_interest_amount=None,
            open_interest_value=None,
            long_short_ratio=1.2,
            updated_at=datetime.now(timezone.utc),
        ),
    )

    assert futures.action == "GO LONG"
    assert result.status == "PASS"
    assert result.allowed


def test_probability_filter_blocks_unfavorable_long_odds() -> None:
    futures, result = apply_do_not_trade_filters(
        _long_plan(),
        Settings(),
        probability_forecast=_probability(
            long_tp_before_sl_probability=0.35,
            long_sl_before_tp_probability=0.42,
        ),
        market_context=_context(),
    )

    assert futures.action == "STAY FLAT"
    assert futures.entry_price is None
    assert result.status == "BLOCKED"
    assert any("TP-before-SL odds" in reason for reason in result.reasons)


def test_market_context_filter_blocks_extreme_upper_range_long() -> None:
    futures, result = apply_do_not_trade_filters(
        _long_plan(),
        Settings(),
        probability_forecast=_probability(),
        market_context=_context(range_position_percent=92.0),
    )

    assert futures.side == "FLAT"
    assert futures.take_profit is None
    assert result.original_action == "GO LONG"
    assert any("upper range" in reason for reason in result.reasons)


def test_disabled_filters_keep_original_plan() -> None:
    settings = Settings(do_not_trade_filters_enabled=False)
    futures, result = apply_do_not_trade_filters(
        _long_plan(),
        settings,
        probability_forecast=_probability(
            long_tp_before_sl_probability=0.10,
            long_sl_before_tp_probability=0.80,
        ),
        market_context=_context(atr_percent=8.0),
    )

    assert futures.action == "GO LONG"
    assert futures.entry_price == pytest.approx(100.0)
    assert result.status == "DISABLED"
