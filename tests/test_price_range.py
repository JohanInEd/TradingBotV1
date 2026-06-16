from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.price_range import PriceRangeSettings, forecast_price_range


def _candles(count: int = 120) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(count):
        price += 0.2
        swing = 2.0 + (index % 5) * 0.1
        rows.append(
            {
                "timestamp": start + timedelta(hours=4 * index),
                "open": price - 0.5,
                "high": price + swing,
                "low": price - swing,
                "close": price,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_forecast_price_range_uses_forward_historical_windows() -> None:
    forecast = forecast_price_range(
        _candles(),
        PriceRangeSettings(
            horizon_hours=24,
            horizon_candles=6,
            lookback_candles=100,
        ),
    )

    assert forecast.horizon_hours == 24
    assert forecast.expected_low < 124.0
    assert forecast.expected_high > 124.0
    assert forecast.support_level < forecast.resistance_level
    assert forecast.sample_size > 80
    assert forecast.confidence == "MEDIUM"


def test_forecast_price_range_reports_percent_moves() -> None:
    forecast = forecast_price_range(_candles())

    assert forecast.downside_percent < 0
    assert forecast.upside_percent > 0
    assert "Forward-window historical quantiles" in forecast.method
