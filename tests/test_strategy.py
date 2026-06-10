from dataclasses import replace
from datetime import datetime, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    MacroAnalysis,
    SentimentAnalysis,
    TechnicalAnalysis,
    TimeframeConfirmation,
)
from btc_trading_bot.strategy import calculate_signal


def _technical(score: float) -> TechnicalAnalysis:
    return TechnicalAnalysis(
        candle_time=datetime.now(timezone.utc),
        close=100.0,
        ema20=101.0,
        ema50=99.0,
        ema_status="Bullish alignment",
        rsi14=60.0,
        rsi_status="Bullish momentum",
        macd=2.0,
        macd_signal=1.0,
        macd_histogram=1.0,
        macd_status="Bullish, strengthening",
        score=score,
    )


def _confirmation(score: float, status: str) -> TimeframeConfirmation:
    return TimeframeConfirmation(
        candle_time=datetime.now(timezone.utc),
        close=100.0,
        status=status,
        score=score,
    )


def test_full_positive_confluence_is_strong_buy() -> None:
    result = calculate_signal(
        _technical(1.0),
        SentimentAnalysis(score=1.0, label="Extremely Bullish"),
        MacroAnalysis(score=1.0, status="WATCHING MACRO", risk_multiplier=1.0),
        Settings(),
    )

    assert result.score == 1.0
    assert result.signal == "STRONG BUY"


def test_defensive_multiplier_blocks_marginal_buy() -> None:
    result = calculate_signal(
        _technical(1.0),
        SentimentAnalysis(score=0.8, label="Bullish"),
        MacroAnalysis(
            score=0.2,
            status="ELEVATED RISK",
            risk_multiplier=0.65,
        ),
        Settings(),
    )

    assert result.raw_score > 0.65
    assert result.score < 0.65
    assert result.signal == "HOLD / NEUTRAL"


def test_full_negative_confluence_is_strong_sell() -> None:
    result = calculate_signal(
        _technical(-1.0),
        SentimentAnalysis(score=-1.0, label="Extremely Bearish"),
        MacroAnalysis(score=-1.0, status="HIGH RISK", risk_multiplier=0.5),
        Settings(),
    )

    assert result.score == -1.0
    assert result.signal == "STRONG SELL"


def test_aligned_timeframes_allow_strong_buy() -> None:
    technical = replace(
        _technical(1.0),
        base_score=0.8,
        daily_trend=_confirmation(0.65, "Bullish alignment"),
        hourly_entry=_confirmation(0.5, "Bullish entry timing"),
    )

    result = calculate_signal(
        technical,
        SentimentAnalysis(score=1.0, label="Extremely Bullish"),
        MacroAnalysis(score=1.0, status="WATCHING MACRO", risk_multiplier=1.0),
        Settings(),
    )

    assert result.signal == "STRONG BUY"


def test_conflicting_daily_trend_blocks_strong_buy() -> None:
    technical = replace(
        _technical(1.0),
        base_score=0.8,
        daily_trend=_confirmation(-0.65, "Bearish alignment"),
        hourly_entry=_confirmation(0.5, "Bullish entry timing"),
    )

    result = calculate_signal(
        technical,
        SentimentAnalysis(score=1.0, label="Extremely Bullish"),
        MacroAnalysis(score=1.0, status="WATCHING MACRO", risk_multiplier=1.0),
        Settings(),
    )

    assert result.score == 1.0
    assert result.signal == "HOLD / NEUTRAL"
