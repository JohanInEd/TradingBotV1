from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.backtest import (
    ProbabilityBacktestSettings,
    forecast_probability,
)


def _trend_candles(count: int = 150, *, step: float = 1.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 300.0 if step < 0 else 100.0
    for index in range(count):
        open_price = price
        close = price + step
        high = max(open_price, close) + abs(step) * 1.5
        low = min(open_price, close) - abs(step) * 0.2
        rows.append(
            {
                "timestamp": start + timedelta(hours=4 * index),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10.0,
            }
        )
        price = close
    return pd.DataFrame(rows)


def test_forecast_probability_reports_bullish_historical_odds() -> None:
    forecast = forecast_probability(
        _trend_candles(step=1.0),
        ProbabilityBacktestSettings(
            horizon_hours=24,
            horizon_candles=6,
            lookback_candles=140,
            min_samples=20,
            max_samples=60,
        ),
        stop_loss_percent=0.01,
        reward_to_risk=1.0,
    )

    assert forecast.horizon_hours == 24
    assert forecast.up_probability == 1.0
    assert forecast.down_probability == 0.0
    assert forecast.long_tp_before_sl_probability == 1.0
    assert forecast.short_sl_before_tp_probability == 1.0
    assert forecast.expected_long_r > 0
    assert forecast.sample_size == 60
    assert forecast.confidence == "MEDIUM"


def test_forecast_probability_reports_bearish_historical_odds() -> None:
    forecast = forecast_probability(
        _trend_candles(step=-1.0),
        ProbabilityBacktestSettings(
            horizon_hours=24,
            horizon_candles=6,
            lookback_candles=140,
            min_samples=20,
            max_samples=60,
        ),
        stop_loss_percent=0.01,
        reward_to_risk=1.0,
    )

    assert forecast.up_probability == 0.0
    assert forecast.down_probability == 1.0
    assert forecast.short_tp_before_sl_probability == 1.0
    assert forecast.long_sl_before_tp_probability == 1.0
    assert forecast.expected_short_r > 0
