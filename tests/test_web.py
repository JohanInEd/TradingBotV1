from dataclasses import replace
from datetime import datetime, timezone

from btc_trading_bot.models import ScenarioForecast, ScenarioPathPoint
from btc_trading_bot.web import _jsonable
from tests.test_app import _evaluation


def test_jsonable_serializes_evaluation_datetimes() -> None:
    payload = _jsonable(_evaluation())

    assert payload["market"]["price"] == 100.0
    assert "price_range" in payload
    assert "probability_forecast" in payload
    assert "scenario_forecast" in payload
    assert "market_context" in payload
    assert "paper_setup" in payload
    assert payload["paper_setup"] is None
    assert payload["signal"]["signal"] == "HOLD / NEUTRAL"
    assert isinstance(payload["evaluated_at"], str)
    assert datetime.fromisoformat(payload["evaluated_at"])


def test_jsonable_serializes_tuples_as_lists() -> None:
    payload = _jsonable(_evaluation())

    assert payload["errors"] == []


def test_jsonable_serializes_scenario_forecast_shape() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scenario = ScenarioForecast(
        horizon_hours=168,
        sample_size=40,
        candidate_count=90,
        confidence="LOW",
        method="Historical scenario from similar setups; not a prediction.",
        generated_at=now,
        up_probability=0.55,
        down_probability=0.45,
        median_path=(
            ScenarioPathPoint(
                time=now,
                price=101.0,
                percent_change=1.0,
            ),
        ),
        lower_band_path=(
            ScenarioPathPoint(
                time=now,
                price=99.0,
                percent_change=-1.0,
            ),
        ),
        upper_band_path=(
            ScenarioPathPoint(
                time=now,
                price=103.0,
                percent_change=3.0,
            ),
        ),
        expected_low=98.0,
        expected_high=104.0,
    )

    payload = _jsonable(replace(_evaluation(), scenario_forecast=scenario))
    forecast = payload["scenario_forecast"]

    assert forecast["horizon_hours"] == 168
    assert forecast["sample_size"] == 40
    assert forecast["up_probability"] == 0.55
    assert forecast["median_path"][0]["price"] == 101.0
    assert datetime.fromisoformat(forecast["median_path"][0]["time"]) == now
