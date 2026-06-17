from datetime import datetime

from btc_trading_bot.web import _jsonable
from tests.test_app import _evaluation


def test_jsonable_serializes_evaluation_datetimes() -> None:
    payload = _jsonable(_evaluation())

    assert payload["market"]["price"] == 100.0
    assert "price_range" in payload
    assert "probability_forecast" in payload
    assert "market_context" in payload
    assert "paper_setup" in payload
    assert payload["paper_setup"] is None
    assert payload["signal"]["signal"] == "HOLD / NEUTRAL"
    assert isinstance(payload["evaluated_at"], str)
    assert datetime.fromisoformat(payload["evaluated_at"])


def test_jsonable_serializes_tuples_as_lists() -> None:
    payload = _jsonable(_evaluation())

    assert payload["errors"] == []
