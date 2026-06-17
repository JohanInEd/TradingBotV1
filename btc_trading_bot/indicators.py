from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from typing import Any

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import BollingerBands

from btc_trading_bot.models import TechnicalAnalysis, TimeframeConfirmation


class IndicatorError(RuntimeError):
    """Raised when indicators cannot be calculated from the supplied candles."""


def analyze_technicals(candles: pd.DataFrame) -> TechnicalAnalysis:
    required = {"timestamp", "close"}
    if not required.issubset(candles.columns) or len(candles) < 60:
        raise IndicatorError("At least 60 candles with timestamp and close are required")

    data = candles.copy()
    close = pd.to_numeric(data["close"], errors="coerce")
    data["ema20"] = EMAIndicator(close=close, window=20).ema_indicator()
    data["ema50"] = EMAIndicator(close=close, window=50).ema_indicator()
    data["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_histogram"] = macd.macd_diff()

    current = data.iloc[-1]
    previous = data.iloc[-2]
    values = (
        current["ema20"],
        current["ema50"],
        current["rsi14"],
        current["macd"],
        current["macd_signal"],
        current["macd_histogram"],
    )
    if any(pd.isna(value) or not math.isfinite(float(value)) for value in values):
        raise IndicatorError("Latest indicator values are incomplete")

    ema_status, ema_score = _ema_signal(current, previous)
    rsi_status, rsi_score = _rsi_signal(float(current["rsi14"]))
    macd_status, macd_score = _macd_signal(current, previous)
    score = _clamp(0.40 * ema_score + 0.25 * rsi_score + 0.35 * macd_score)

    candle_time = current["timestamp"]
    if hasattr(candle_time, "to_pydatetime"):
        candle_time = candle_time.to_pydatetime()

    return TechnicalAnalysis(
        candle_time=candle_time,
        close=float(current["close"]),
        ema20=float(current["ema20"]),
        ema50=float(current["ema50"]),
        ema_status=ema_status,
        rsi14=float(current["rsi14"]),
        rsi_status=rsi_status,
        macd=float(current["macd"]),
        macd_signal=float(current["macd_signal"]),
        macd_histogram=float(current["macd_histogram"]),
        macd_status=macd_status,
        score=score,
    )


def analyze_multi_timeframe(
    four_hour_candles: pd.DataFrame,
    daily_candles: pd.DataFrame,
    hourly_candles: pd.DataFrame,
    primary_weight: float = 0.60,
    daily_weight: float = 0.25,
    hourly_weight: float = 0.15,
) -> TechnicalAnalysis:
    total_weight = primary_weight + daily_weight + hourly_weight
    if total_weight <= 0:
        raise IndicatorError("Multi-timeframe weights must have a positive total")

    primary = analyze_technicals(four_hour_candles)
    daily = analyze_technicals(daily_candles)
    hourly = analyze_technicals(hourly_candles)

    daily_score = _ema_score_from_status(daily.ema_status)
    combined_score = _clamp(
        (
            primary.score * primary_weight
            + daily_score * daily_weight
            + hourly.score * hourly_weight
        )
        / total_weight
    )

    return replace(
        primary,
        score=combined_score,
        base_score=primary.score,
        daily_trend=TimeframeConfirmation(
            candle_time=daily.candle_time,
            close=daily.close,
            status=daily.ema_status,
            score=daily_score,
        ),
        hourly_entry=TimeframeConfirmation(
            candle_time=hourly.candle_time,
            close=hourly.close,
            status=_entry_status(hourly.score),
            score=hourly.score,
        ),
    )


def build_chart_indicators(
    candles: pd.DataFrame, limit: int = 120
) -> list[dict[str, Any]]:
    required = {"timestamp", "close"}
    if not required.issubset(candles.columns) or candles.empty:
        return []

    data = candles.copy().sort_values("timestamp").tail(max(1, limit))
    close = pd.to_numeric(data["close"], errors="coerce")
    high = _numeric_or_close(data, "high", close)
    low = _numeric_or_close(data, "low", close)
    open_ = _numeric_or_close(data, "open", close)
    raw_volume = data["volume"] if "volume" in data else pd.Series(0, index=data.index)
    volume = pd.to_numeric(raw_volume, errors="coerce").fillna(0)

    data["open"] = open_
    data["high"] = high
    data["low"] = low
    data["close"] = close
    data["volume"] = volume
    data["ema20"] = EMAIndicator(close=close, window=20).ema_indicator()
    data["ema50"] = EMAIndicator(close=close, window=50).ema_indicator()
    data["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_histogram"] = macd.macd_diff()
    bands = BollingerBands(close=close, window=20, window_dev=2)
    data["bollinger_high"] = bands.bollinger_hband()
    data["bollinger_mid"] = bands.bollinger_mavg()
    data["bollinger_low"] = bands.bollinger_lband()
    typical_price = (high + low + close) / 3
    rolling_volume = volume.rolling(20, min_periods=1).sum()
    data["vwap20"] = (
        (typical_price * volume).rolling(20, min_periods=1).sum()
        / rolling_volume.replace(0, pd.NA)
    ).fillna(close)
    data["adx14"] = ADXIndicator(
        high=high, low=low, close=close, window=14
    ).adx()

    rows: list[dict[str, Any]] = []
    for item in data.itertuples(index=False):
        timestamp = getattr(item, "timestamp")
        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()
        rows.append(
            {
                "time": timestamp.isoformat()
                if isinstance(timestamp, datetime)
                else str(timestamp),
                "open": _finite_or_none(getattr(item, "open")),
                "high": _finite_or_none(getattr(item, "high")),
                "low": _finite_or_none(getattr(item, "low")),
                "close": _finite_or_none(getattr(item, "close")),
                "volume": _finite_or_none(getattr(item, "volume")),
                "ema20": _finite_or_none(getattr(item, "ema20")),
                "ema50": _finite_or_none(getattr(item, "ema50")),
                "vwap": _finite_or_none(getattr(item, "vwap20")),
                "bollinger_high": _finite_or_none(getattr(item, "bollinger_high")),
                "bollinger_mid": _finite_or_none(getattr(item, "bollinger_mid")),
                "bollinger_low": _finite_or_none(getattr(item, "bollinger_low")),
                "rsi14": _finite_or_none(getattr(item, "rsi14")),
                "macd": _finite_or_none(getattr(item, "macd")),
                "macd_signal": _finite_or_none(getattr(item, "macd_signal")),
                "macd_histogram": _finite_or_none(getattr(item, "macd_histogram")),
                "adx14": _finite_or_none(getattr(item, "adx14")),
            }
        )
    return rows


def _numeric_or_close(
    data: pd.DataFrame, column: str, close: pd.Series
) -> pd.Series:
    if column not in data:
        return close
    return pd.to_numeric(data[column], errors="coerce").fillna(close)


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ema_signal(current: pd.Series, previous: pd.Series) -> tuple[str, float]:
    bullish = current["ema20"] > current["ema50"]
    was_bullish = previous["ema20"] > previous["ema50"]
    if bullish and not was_bullish:
        return "Bullish crossover", 1.0
    if not bullish and was_bullish:
        return "Bearish crossover", -1.0
    return ("Bullish alignment", 0.65) if bullish else ("Bearish alignment", -0.65)


def _rsi_signal(value: float) -> tuple[str, float]:
    if value <= 30:
        return "Oversold", 1.0
    if value >= 70:
        return "Overbought", -1.0
    if value >= 55:
        return "Bullish momentum", 0.35
    if value <= 45:
        return "Bearish momentum", -0.35
    return "Neutral", 0.0


def _macd_signal(current: pd.Series, previous: pd.Series) -> tuple[str, float]:
    bullish = current["macd"] > current["macd_signal"]
    was_bullish = previous["macd"] > previous["macd_signal"]
    histogram_rising = current["macd_histogram"] > previous["macd_histogram"]
    if bullish and not was_bullish:
        return "Bullish crossover", 1.0
    if not bullish and was_bullish:
        return "Bearish crossover", -1.0
    if bullish:
        return ("Bullish, strengthening", 0.75) if histogram_rising else (
            "Bullish, weakening",
            0.45,
        )
    return ("Bearish, weakening", -0.45) if histogram_rising else (
        "Bearish, strengthening",
        -0.75,
    )


def _ema_score_from_status(status: str) -> float:
    magnitude = 1.0 if "crossover" in status.lower() else 0.65
    return magnitude if "bullish" in status.lower() else -magnitude


def _entry_status(score: float) -> str:
    if score > 0.10:
        return "Bullish entry timing"
    if score < -0.10:
        return "Bearish entry timing"
    return "Neutral entry timing"


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
