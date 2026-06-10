from __future__ import annotations

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    MacroAnalysis,
    SentimentAnalysis,
    SignalResult,
    TechnicalAnalysis,
)


def calculate_signal(
    technical: TechnicalAnalysis,
    sentiment: SentimentAnalysis,
    macro: MacroAnalysis,
    settings: Settings,
) -> SignalResult:
    technical_contribution = technical.score * settings.technical_weight
    sentiment_contribution = sentiment.score * settings.sentiment_weight
    macro_contribution = macro.score * settings.macro_weight
    raw_score = _clamp(
        technical_contribution + sentiment_contribution + macro_contribution
    )

    risk_multiplier = macro.risk_multiplier
    adjusted_score = raw_score
    if raw_score > 0 and risk_multiplier < 1.0:
        adjusted_score = raw_score * risk_multiplier
    adjusted_score = _clamp(adjusted_score)

    if adjusted_score > settings.buy_threshold:
        signal = "STRONG BUY"
    elif adjusted_score < settings.sell_threshold:
        signal = "STRONG SELL"
    else:
        signal = "HOLD / NEUTRAL"

    if signal == "STRONG BUY" and not _timeframes_confirm(technical, bullish=True):
        signal = "HOLD / NEUTRAL"
    elif signal == "STRONG SELL" and not _timeframes_confirm(
        technical, bullish=False
    ):
        signal = "HOLD / NEUTRAL"

    return SignalResult(
        signal=signal,
        raw_score=raw_score,
        score=adjusted_score,
        technical_contribution=technical_contribution,
        sentiment_contribution=sentiment_contribution,
        macro_contribution=macro_contribution,
        risk_multiplier=risk_multiplier,
    )


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _timeframes_confirm(
    technical: TechnicalAnalysis, *, bullish: bool
) -> bool:
    daily = technical.daily_trend
    hourly = technical.hourly_entry
    if daily is None and hourly is None:
        return True
    if daily is None or hourly is None:
        return False

    primary_score = (
        technical.base_score
        if technical.base_score is not None
        else technical.score
    )
    scores = (primary_score, daily.score, hourly.score)
    return all(score > 0 for score in scores) if bullish else all(
        score < 0 for score in scores
    )
