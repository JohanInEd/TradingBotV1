from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from btc_trading_bot.scenario_map import ScenarioMapSettings, forecast_scenario_map


def _trend_candles(count: int = 190, *, step: float = 1.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
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


def _alternating_candles(count: int = 140) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        open_price = 101.0 if index % 2 else 100.0
        close = 102.0 if index % 2 else 99.0
        rows.append(
            {
                "timestamp": start + timedelta(hours=4 * index),
                "open": open_price,
                "high": max(open_price, close) + 1.0,
                "low": min(open_price, close) - 1.0,
                "close": close,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_forecast_scenario_map_returns_none_for_insufficient_data() -> None:
    forecast = forecast_scenario_map(
        _trend_candles(40),
        ScenarioMapSettings(min_samples=5, max_samples=10),
    )

    assert forecast is None


def test_forecast_scenario_map_builds_7_day_path_distribution() -> None:
    forecast = forecast_scenario_map(
        _trend_candles(),
        ScenarioMapSettings(
            horizon_hours=168,
            horizon_candles=42,
            lookback_candles=180,
            min_samples=20,
            max_samples=60,
        ),
    )

    assert forecast is not None
    assert forecast.horizon_hours == 168
    assert forecast.sample_size == 60
    assert forecast.candidate_count >= forecast.sample_size
    assert len(forecast.median_path) == 42
    assert len(forecast.lower_band_path) == 42
    assert len(forecast.upper_band_path) == 42
    for lower, median, upper in zip(
        forecast.lower_band_path,
        forecast.median_path,
        forecast.upper_band_path,
    ):
        assert lower.price <= median.price <= upper.price
    assert forecast.expected_low < forecast.expected_high
    assert "not a prediction" in forecast.method


def test_forecast_scenario_map_calculates_direction_probabilities() -> None:
    candles = _alternating_candles()
    forecast = forecast_scenario_map(
        candles,
        ScenarioMapSettings(
            horizon_hours=4,
            horizon_candles=1,
            lookback_candles=120,
            min_samples=10,
            max_samples=500,
        ),
    )

    assert forecast is not None
    closes = candles["close"].tolist()
    first_index = len(closes) - 1 - forecast.candidate_count
    candidate_indexes = range(first_index, len(closes) - 1)
    expected_up = sum(closes[index + 1] > closes[index] for index in candidate_indexes)
    expected_down = sum(
        closes[index + 1] < closes[index] for index in candidate_indexes
    )

    assert forecast.sample_size == forecast.candidate_count
    assert forecast.up_probability == pytest.approx(expected_up / forecast.sample_size)
    assert forecast.down_probability == pytest.approx(
        expected_down / forecast.sample_size
    )
