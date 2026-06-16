from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from btc_trading_bot.models import PriceRangeForecast


class PriceRangeError(RuntimeError):
    """Raised when a historical price range cannot be calculated."""


@dataclass(frozen=True, slots=True)
class PriceRangeSettings:
    horizon_hours: int = 24
    horizon_candles: int = 6
    lookback_candles: int = 180
    lower_quantile: float = 0.20
    upper_quantile: float = 0.80


def forecast_price_range(
    candles: pd.DataFrame,
    settings: PriceRangeSettings | None = None,
) -> PriceRangeForecast:
    settings = settings or PriceRangeSettings()
    required = {"timestamp", "high", "low", "close"}
    if not required.issubset(candles.columns):
        raise PriceRangeError("Candles must include timestamp, high, low, and close")
    if len(candles) < max(60, settings.horizon_candles + 30):
        raise PriceRangeError("At least 60 candles are required for range analysis")

    data = candles.tail(settings.lookback_candles + settings.horizon_candles).copy()
    for column in ("high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(data) < max(60, settings.horizon_candles + 30):
        raise PriceRangeError("Not enough valid candles for range analysis")

    current_close = float(data["close"].iloc[-1])
    if current_close <= 0:
        raise PriceRangeError("Latest close must be greater than zero")

    downside_moves: list[float] = []
    upside_moves: list[float] = []
    last_start = len(data) - settings.horizon_candles - 1
    for start in range(0, last_start):
        start_close = float(data["close"].iloc[start])
        if start_close <= 0:
            continue
        future = data.iloc[start + 1 : start + 1 + settings.horizon_candles]
        if len(future) < settings.horizon_candles:
            continue
        downside_moves.append(float(future["low"].min()) / start_close - 1.0)
        upside_moves.append(float(future["high"].max()) / start_close - 1.0)

    if not downside_moves or not upside_moves:
        raise PriceRangeError("No historical forward windows were available")

    downside = float(pd.Series(downside_moves).quantile(settings.lower_quantile))
    upside = float(pd.Series(upside_moves).quantile(settings.upper_quantile))
    expected_low = min(current_close, current_close * (1.0 + downside))
    expected_high = max(current_close, current_close * (1.0 + upside))

    support_window = data.tail(min(settings.lookback_candles, len(data)))
    support = float(support_window["low"].min())
    resistance = float(support_window["high"].max())

    return PriceRangeForecast(
        horizon_hours=settings.horizon_hours,
        expected_low=expected_low,
        expected_high=expected_high,
        support_level=support,
        resistance_level=resistance,
        downside_percent=downside * 100.0,
        upside_percent=upside * 100.0,
        confidence=_confidence(len(downside_moves)),
        sample_size=len(downside_moves),
        method=(
            "Forward-window historical quantiles from recent 4h candles "
            f"({settings.lower_quantile:.0%}/{settings.upper_quantile:.0%})."
        ),
        generated_at=datetime.now(timezone.utc),
    )


def _confidence(sample_size: int) -> str:
    if sample_size >= 120:
        return "HIGH"
    if sample_size >= 60:
        return "MEDIUM"
    return "LOW"
