from __future__ import annotations

import math

import pandas as pd

from btc_trading_bot.models import MarketContext


class MarketContextError(RuntimeError):
    """Raised when market context cannot be calculated from candle data."""


def analyze_market_context(candles: pd.DataFrame) -> MarketContext:
    required = {"timestamp", "close"}
    if not required.issubset(candles.columns) or len(candles) < 60:
        raise MarketContextError("At least 60 candles with timestamp and close are required")

    data = candles.copy()
    close = pd.to_numeric(data["close"], errors="coerce")
    high = (
        pd.to_numeric(data["high"], errors="coerce")
        if "high" in data
        else close.copy()
    )
    low = (
        pd.to_numeric(data["low"], errors="coerce")
        if "low" in data
        else close.copy()
    )
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14).mean()
    returns = close.pct_change()
    realized_volatility = returns.rolling(20).std() * math.sqrt(6) * 100
    moving_average = close.rolling(20).mean()
    standard_deviation = close.rolling(20).std()
    bollinger_width = (standard_deviation * 4 / moving_average) * 100
    rolling_high = high.rolling(50).max()
    rolling_low = low.rolling(50).min()
    trend_strength = ((close.rolling(20).mean() - close.rolling(50).mean()).abs() / close) * 100

    current_index = data.index[-1]
    current_close = float(close.loc[current_index])
    current_atr = float(atr.loc[current_index])
    current_realized = float(realized_volatility.loc[current_index])
    current_width = float(bollinger_width.loc[current_index])
    current_high = float(rolling_high.loc[current_index])
    current_low = float(rolling_low.loc[current_index])
    current_trend_strength = float(trend_strength.loc[current_index])

    values = (
        current_close,
        current_atr,
        current_realized,
        current_width,
        current_high,
        current_low,
        current_trend_strength,
    )
    if any(pd.isna(value) or not math.isfinite(value) for value in values):
        raise MarketContextError("Latest market context values are incomplete")

    atr_percent = current_atr / current_close * 100
    range_span = current_high - current_low
    range_position = (
        (current_close - current_low) / range_span * 100 if range_span > 0 else 50.0
    )
    volatility_regime = _volatility_regime(atr_percent, current_realized)
    structure_regime = _structure_regime(
        trend_strength_percent=current_trend_strength,
        bollinger_width_percent=current_width,
        range_position_percent=range_position,
    )
    candle_time = data.iloc[-1]["timestamp"]
    if hasattr(candle_time, "to_pydatetime"):
        candle_time = candle_time.to_pydatetime()

    return MarketContext(
        volatility_regime=volatility_regime,
        structure_regime=structure_regime,
        atr_percent=atr_percent,
        realized_volatility_percent=current_realized,
        bollinger_width_percent=current_width,
        range_position_percent=max(0.0, min(100.0, range_position)),
        trend_strength_percent=current_trend_strength,
        reason=_reason(
            volatility_regime=volatility_regime,
            structure_regime=structure_regime,
            atr_percent=atr_percent,
            realized_volatility_percent=current_realized,
            bollinger_width_percent=current_width,
            range_position_percent=range_position,
            trend_strength_percent=current_trend_strength,
        ),
        updated_at=candle_time,
    )


def _volatility_regime(atr_percent: float, realized_volatility_percent: float) -> str:
    combined = max(atr_percent, realized_volatility_percent)
    if combined >= 3.0:
        return "HIGH VOLATILITY"
    if combined >= 1.6:
        return "ELEVATED VOLATILITY"
    if combined <= 0.7:
        return "COMPRESSED VOLATILITY"
    return "NORMAL VOLATILITY"


def _structure_regime(
    *,
    trend_strength_percent: float,
    bollinger_width_percent: float,
    range_position_percent: float,
) -> str:
    if trend_strength_percent >= 2.0 and range_position_percent >= 70:
        return "TRENDING UP"
    if trend_strength_percent >= 2.0 and range_position_percent <= 30:
        return "TRENDING DOWN"
    if bollinger_width_percent <= 3.0:
        return "RANGE COMPRESSION"
    if 35 <= range_position_percent <= 65:
        return "MID-RANGE"
    if range_position_percent > 65:
        return "UPPER RANGE"
    return "LOWER RANGE"


def _reason(
    *,
    volatility_regime: str,
    structure_regime: str,
    atr_percent: float,
    realized_volatility_percent: float,
    bollinger_width_percent: float,
    range_position_percent: float,
    trend_strength_percent: float,
) -> str:
    return (
        f"{volatility_regime.lower()} with ATR {atr_percent:.2f}% and "
        f"realized vol {realized_volatility_percent:.2f}%; "
        f"{structure_regime.lower()} from {trend_strength_percent:.2f}% trend "
        f"spread, {bollinger_width_percent:.2f}% band width, and "
        f"{range_position_percent:.0f}% 50-candle range position."
    )
