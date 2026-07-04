from dataclasses import replace
from datetime import datetime, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.models import ScenarioForecast, ScenarioPathPoint
from btc_trading_bot.web import (
    _jsonable,
    build_confidence_score,
    build_simulator_summary,
)
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


def test_confidence_score_serializes_for_web_payload() -> None:
    confidence = build_confidence_score(_evaluation())
    payload = _jsonable(confidence)

    assert payload["label"] in {"LOW", "MEDIUM", "HIGH"}
    assert 0 <= payload["score"] <= 1
    assert payload["action"] in {"GO LONG", "GO SHORT", "STAY FLAT"}
    assert len(payload["factors"]) == 5
    assert payload["factors"][0]["label"] == "Signal strength"


def test_simulator_summary_reports_missing_configuration() -> None:
    summary = build_simulator_summary(Settings(history_db_path=None))

    assert summary["status"] == "not_configured"
    assert "BOT_HISTORY_DB_PATH" in summary["message"]


class _FakeService:
    def __init__(self, rows):
        self._rows = rows

    def journal_rows(self):
        return list(self._rows)

    def paper_setup_report(self):
        from btc_trading_bot.paper_setups import analyze_setup_rows

        return analyze_setup_rows(list(self._rows), settings=Settings())

    def portfolio_state(self):
        from btc_trading_bot.portfolio import build_portfolio_state

        return build_portfolio_state(list(self._rows), settings=Settings())


def _setup_row(symbol: str, outcome: str, candle: str) -> dict:
    return {
        "symbol": symbol,
        "timeframe": "4h",
        "side": "LONG",
        "futures_action": "GO LONG",
        "entry": 100.0,
        "stop_loss": 98.5,
        "take_profit": 103.0,
        "reward_to_risk": 2.0,
        "close_price": 100.0,
        "technical_score": 0.7,
        "score_bucket": ">= +0.65",
        "market_regime": "TRENDING UP",
        "volatility_regime": "NORMAL VOLATILITY",
        "trend_range_context": "TRENDING UP",
        "quantity_btc": 1.0,
        "notional": 100.0,
        "max_loss": 50.0,
        "leverage": 1,
        "outcome": outcome,
        "entry_reached": outcome != "OPEN",
        "r_multiple": 2.0 if outcome == "TP" else (-1.0 if outcome == "SL" else None),
        "outcome_at": f"{candle[:10]}T20:00:00+00:00" if outcome != "OPEN" else None,
        "outcome_price": 103.0 if outcome == "TP" else None,
        "duration_hours": 8.0 if outcome != "OPEN" else None,
        "closed_candle_at": candle,
        "signal_time": candle,
        "expires_at": f"{candle[:10]}T23:59:00+00:00",
        "signal_json": "{}",
    }


def test_setups_payload_filters_and_compacts() -> None:
    from btc_trading_bot.web import WebStateService

    rows = [
        _setup_row("BTC/USDT:USDT", "TP", "2026-06-01T08:00:00+00:00"),
        _setup_row("ETH/USDT:USDT", "SL", "2026-06-02T08:00:00+00:00"),
        _setup_row("BTC/USDT:USDT", "OPEN", "2026-06-03T08:00:00+00:00"),
    ]
    state = WebStateService.__new__(WebStateService)
    state.service = _FakeService(rows)

    payload = state.setups_payload({"symbol": ["BTC/USDT:USDT"], "limit": ["10"]})

    assert payload["status"] == "ok"
    assert payload["total"] == 2
    assert [row["outcome"] for row in payload["setups"]] == ["OPEN", "TP"]
    assert "signal_json" not in payload["setups"][0]

    outcome_only = state.setups_payload({"outcome": ["SL"]})
    assert outcome_only["total"] == 1
    assert outcome_only["setups"][0]["symbol"] == "ETH/USDT:USDT"


def test_performance_and_portfolio_payloads() -> None:
    from btc_trading_bot.web import WebStateService

    rows = [
        _setup_row("BTC/USDT:USDT", "TP", "2026-06-01T08:00:00+00:00"),
        _setup_row("BTC/USDT:USDT", "OPEN", "2026-06-03T08:00:00+00:00"),
    ]
    state = WebStateService.__new__(WebStateService)
    state.service = _FakeService(rows)

    performance = state.performance_payload()
    assert performance["status"] == "ok"
    assert performance["journal"]["total_setups"] == 2
    assert performance["journal"]["equity_curve"][0]["outcome"] == "START"
    assert performance["portfolio"]["open_positions"] == 1

    portfolio = state.portfolio_payload()
    assert portfolio["portfolio"]["open_symbols"] == ["BTC/USDT:USDT"]

    drift = state.drift_payload()
    assert drift["status"] == "ok"
    assert drift["drift"]["status"] == "INSUFFICIENT DATA"
