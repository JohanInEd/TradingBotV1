from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.paper_setups import (
    OUTCOME_EXPIRED,
    OUTCOME_OPEN,
    OUTCOME_SL,
    OUTCOME_TP,
    PaperSetupJournal,
    analyze_setup_rows,
    build_current_paper_setup,
    format_paper_setup_report,
    resolve_setup_outcome,
)
from btc_trading_bot.web import _jsonable
from tests.test_signal_journal import _evaluation


SETTINGS = Settings(
    stop_loss_percent=0.01,
    reward_to_risk=2.0,
    paper_setup_horizon_hours=24,
)
EXCHANGE = "binanceusdm"
SYMBOL = "BTC/USDT:USDT"
TIMEFRAME = "4h"


def _paper_evaluation(
    *,
    closed_at: datetime,
    signal_name: str = "STRONG BUY",
    close: float = 100.0,
):
    evaluation = _evaluation(
        closed_at=closed_at,
        close=close,
        high=close + 0.5,
        low=close - 0.5,
        signal_name=signal_name,
    )
    paper_setup = build_current_paper_setup(
        futures=evaluation.futures,
        technical=evaluation.technical,
        evaluated_at=evaluation.evaluated_at,
        settings=SETTINGS,
        market_context=evaluation.market_context,
        probability_forecast=evaluation.probability_forecast,
    )
    return replace(evaluation, paper_setup=paper_setup)


def _record_setup(journal: PaperSetupJournal, evaluation) -> None:
    assert journal.record(
        evaluation,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        settings=SETTINGS,
    )


def test_paper_setup_journal_persists_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "paper-setups.sqlite"
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    evaluation = _paper_evaluation(closed_at=closed_at)

    with PaperSetupJournal(path, horizon_hours=24) as journal:
        _record_setup(journal, evaluation)
        assert not journal.record(
            evaluation,
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            settings=SETTINGS,
        )
        rows = journal.load_setups()

    assert len(rows) == 1
    row = rows[0]
    assert row["exchange"] == EXCHANGE
    assert row["symbol"] == SYMBOL
    assert row["side"] == "LONG"
    assert row["entry"] == pytest.approx(100.0)
    assert row["stop_loss"] == pytest.approx(99.0)
    assert row["take_profit"] == pytest.approx(102.0)
    assert row["outcome"] == OUTCOME_OPEN
    assert row["score_bucket"] == ">= +0.65"
    assert "not financial advice" in row["setup"]["disclaimer"]


def test_paper_setup_resolves_take_profit_from_public_candle(tmp_path) -> None:
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    with PaperSetupJournal(tmp_path / "paper.sqlite", horizon_hours=24) as journal:
        _record_setup(journal, _paper_evaluation(closed_at=closed_at))

        journal.resolve_with_candles(
            [
                {
                    "timestamp": closed_at + timedelta(hours=4),
                    "high": 102.5,
                    "low": 99.5,
                    "close": 102.1,
                }
            ],
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )
        row = journal.load_setups()[0]

    assert row["entry_reached"]
    assert row["outcome"] == OUTCOME_TP
    assert row["outcome_price"] == pytest.approx(102.0)
    assert row["r_multiple"] == pytest.approx(2.0)
    assert row["duration_hours"] == pytest.approx(4.0)


def test_paper_setup_conservative_same_candle_rule_prefers_stop(tmp_path) -> None:
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    with PaperSetupJournal(tmp_path / "paper.sqlite", horizon_hours=24) as journal:
        _record_setup(journal, _paper_evaluation(closed_at=closed_at))

        journal.resolve_with_candles(
            [
                {
                    "timestamp": closed_at + timedelta(hours=4),
                    "high": 103.0,
                    "low": 98.5,
                    "close": 101.0,
                }
            ],
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )
        row = journal.load_setups()[0]

    assert row["outcome"] == OUTCOME_SL
    assert row["outcome_price"] == pytest.approx(99.0)
    assert row["r_multiple"] == pytest.approx(-1.0)
    assert "TP and SL are both inside one candle" in row["same_candle_rule"]


def test_paper_setup_expires_after_configured_horizon(tmp_path) -> None:
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    with PaperSetupJournal(tmp_path / "paper.sqlite", horizon_hours=24) as journal:
        _record_setup(journal, _paper_evaluation(closed_at=closed_at))

        journal.resolve_with_candles(
            [
                {
                    "timestamp": closed_at + timedelta(hours=24),
                    "high": 100.5,
                    "low": 99.5,
                    "close": 100.25,
                }
            ],
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
        )
        row = journal.load_setups()[0]

    assert row["outcome"] == OUTCOME_EXPIRED
    assert row["r_multiple"] == pytest.approx(0.25)
    assert row["duration_hours"] == pytest.approx(24.0)


def test_resolver_keeps_unentered_setup_open_before_horizon() -> None:
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    setup = {
        "outcome": OUTCOME_OPEN,
        "entry_reached": False,
        "closed_candle_at": closed_at.isoformat(),
        "expires_at": (closed_at + timedelta(hours=24)).isoformat(),
        "side": "SHORT",
        "entry": 100.0,
        "stop_loss": 101.0,
        "take_profit": 98.0,
    }

    resolution = resolve_setup_outcome(
        setup,
        {
            "time": closed_at + timedelta(hours=4),
            "high": 97.5,
            "low": 96.0,
            "close": 97.0,
        },
        horizon_hours=24,
    )

    assert not resolution.changed
    assert resolution.outcome == OUTCOME_OPEN
    assert not resolution.entry_reached


def test_paper_setup_analyzer_summary_and_groups() -> None:
    rows = [
        {
            "side": "LONG",
            "score_bucket": ">= +0.65",
            "market_regime": "NORMAL VOLATILITY / TRENDING UP",
            "volatility_regime": "NORMAL VOLATILITY",
            "trend_range_context": "TRENDING UP",
            "outcome": OUTCOME_TP,
            "r_multiple": 2.0,
            "duration_hours": 4.0,
        },
        {
            "side": "SHORT",
            "score_bucket": "<= -0.65",
            "market_regime": "ELEVATED VOLATILITY / TRENDING DOWN",
            "volatility_regime": "ELEVATED VOLATILITY",
            "trend_range_context": "TRENDING DOWN",
            "outcome": OUTCOME_SL,
            "r_multiple": -1.0,
            "duration_hours": 8.0,
        },
        {
            "side": "LONG",
            "score_bucket": ">= +0.65",
            "market_regime": "NORMAL VOLATILITY / TRENDING UP",
            "volatility_regime": "NORMAL VOLATILITY",
            "trend_range_context": "TRENDING UP",
            "outcome": OUTCOME_OPEN,
        },
    ]

    report = analyze_setup_rows(rows)
    output = format_paper_setup_report(report)

    assert report.total_setups == 3
    assert report.overall.open_count == 1
    assert report.overall.tp_count == 1
    assert report.overall.sl_count == 1
    assert report.overall.win_rate == pytest.approx(0.5)
    assert report.overall.expected_r == pytest.approx(0.5)
    assert report.overall.average_time_to_outcome_hours == pytest.approx(6.0)
    assert report.groups["side"]["LONG"].total_setups == 2
    assert "Overall: total=3 open=1 TP=1 SL=1 expired=0" in output
    assert "By volatility regime:" in output


def test_web_api_payload_includes_current_paper_setup_shape() -> None:
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    payload = _jsonable(_paper_evaluation(closed_at=closed_at))

    setup = payload["paper_setup"]
    assert setup["label"] == "paper setup"
    assert setup["action"] == "GO LONG"
    assert setup["entry_price"] == pytest.approx(100.0)
    assert setup["stop_loss"] == pytest.approx(99.0)
    assert setup["take_profit"] == pytest.approx(102.0)
    assert setup["reward_to_risk"] == pytest.approx(2.0)
    assert setup["max_loss"] == pytest.approx(25.0)
    assert "BTC" in setup["position_estimate"]
    assert "no order placed" in setup["disclaimer"]
    assert "not financial advice" in setup["disclaimer"]
