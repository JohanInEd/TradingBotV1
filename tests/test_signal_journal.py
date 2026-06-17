import json
from datetime import datetime, timedelta, timezone

import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.models import (
    Evaluation,
    MacroAnalysis,
    MarketContext,
    MarketSnapshot,
    SentimentAnalysis,
    SignalResult,
    TechnicalAnalysis,
)
from btc_trading_bot.signal_journal import (
    SignalJournalRecorder,
    analyze_records,
    build_journal_record,
    format_report,
)


def _signal(name: str, score: float) -> SignalResult:
    return SignalResult(
        signal=name,
        raw_score=score,
        score=score,
        technical_contribution=score * 0.4,
        sentiment_contribution=0.0,
        macro_contribution=0.0,
        risk_multiplier=1.0,
    )


def _evaluation(
    *,
    closed_at: datetime,
    close: float,
    high: float,
    low: float,
    signal_name: str = "STRONG BUY",
) -> Evaluation:
    score = 0.8 if signal_name == "STRONG BUY" else -0.8
    settings = Settings(stop_loss_percent=0.01, reward_to_risk=2.0)
    market = MarketSnapshot(
        exchange="Binance USD-M",
        symbol="BTC/USDT:USDT",
        price=close,
        change_24h=1.2,
        timestamp=closed_at,
    )
    technical = TechnicalAnalysis(
        candle_time=closed_at,
        close=close,
        ema20=close + score,
        ema50=close - score,
        ema_status="Bullish alignment" if score > 0 else "Bearish alignment",
        rsi14=60.0 if score > 0 else 40.0,
        rsi_status="Bullish momentum" if score > 0 else "Bearish momentum",
        macd=1.0 if score > 0 else -1.0,
        macd_signal=0.5 if score > 0 else -0.5,
        macd_histogram=0.5 if score > 0 else -0.5,
        macd_status="Bullish, strengthening"
        if score > 0
        else "Bearish, strengthening",
        score=score,
        base_score=score,
        open=close,
        high=high,
        low=low,
    )
    signal = _signal(signal_name, score)
    futures = build_futures_recommendation(signal, market, settings)
    return Evaluation(
        market=market,
        technical=technical,
        sentiment=SentimentAnalysis(score=0.3, label="Bullish"),
        macro=MacroAnalysis(
            score=0.0,
            status="NO MAJOR ALERTS",
            risk_multiplier=1.0,
        ),
        signal=signal,
        futures=futures,
        evaluated_at=closed_at + timedelta(seconds=10),
        next_analysis_at=closed_at + timedelta(hours=4),
        market_context=MarketContext(
            volatility_regime="NORMAL VOLATILITY",
            structure_regime="TRENDING UP",
            atr_percent=1.2,
            realized_volatility_percent=1.1,
            bollinger_width_percent=4.0,
            range_position_percent=75.0,
            trend_strength_percent=2.5,
            reason="Synthetic context",
            updated_at=closed_at,
        ),
    )


def _record(evaluation: Evaluation) -> dict:
    return build_journal_record(
        evaluation,
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="4h",
        settings=Settings(stop_loss_percent=0.01, reward_to_risk=2.0),
    )


def test_signal_journal_recorder_appends_closed_candle_once(tmp_path) -> None:
    path = tmp_path / "signals.jsonl"
    recorder = SignalJournalRecorder(path)
    closed_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    evaluation = _evaluation(
        closed_at=closed_at,
        close=100.0,
        high=101.0,
        low=99.5,
    )

    assert recorder.record(
        evaluation,
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="4h",
        settings=Settings(stop_loss_percent=0.01, reward_to_risk=2.0),
    )
    assert not recorder.record(
        evaluation,
        exchange="binanceusdm",
        symbol="BTC/USDT:USDT",
        timeframe="4h",
        settings=Settings(stop_loss_percent=0.01, reward_to_risk=2.0),
    )

    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["closed_candle_at"] == closed_at.isoformat()
    assert payload["candle"]["high"] == 101.0
    assert payload["signal"]["signal"] == "STRONG BUY"
    assert payload["futures"]["action"] == "GO LONG"
    assert payload["paper_risk"]["long"]["take_profit"] == pytest.approx(102.0)
    assert payload["paper_risk"]["short"]["stop_loss"] == pytest.approx(101.0)


def test_signal_journal_analyzer_reports_direction_tp_sl_and_groups() -> None:
    start = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    closes = [100.0, 102.5, 102.0, 101.5, 102.0, 102.4, 103.0]
    highs = [100.5, 103.0, 102.5, 102.0, 102.5, 103.0, 103.4]
    lows = [99.5, 100.0, 101.0, 100.9, 101.2, 101.8, 102.0]
    records = [
        _record(
            _evaluation(
                closed_at=start + timedelta(hours=4 * index),
                close=close,
                high=highs[index],
                low=lows[index],
            )
        )
        for index, close in enumerate(closes)
    ]

    report = analyze_records(records)
    output = format_report(report)

    assert report.overall.sample_count == 1
    assert report.pending_count == 6
    assert report.overall.directional_count == 1
    assert report.overall.direction_accuracy == 1.0
    assert report.overall.win_rate == 1.0
    assert report.overall.expected_r == pytest.approx(2.0)
    assert report.overall.long_tp_count == 1
    assert report.overall.short_sl_count == 1
    assert report.groups["signal"]["STRONG BUY"].sample_count == 1
    assert "Completed 24h samples: 1 (6 pending)" in output
    assert "Overall: n=1 directional=1 dir=100.0% win=100.0% expR=+2.00" in output
    assert "By signal:" in output
