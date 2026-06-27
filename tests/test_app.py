from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.app import (
    _apply_news_refresh,
    _apply_stream_events,
    _configure_console_encoding,
    _market_is_stale,
    _probability_candles_for_backtest,
)
from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    Evaluation,
    MacroAnalysis,
    MarketSnapshot,
    SentimentAnalysis,
    TechnicalAnalysis,
)
from btc_trading_bot.strategy import calculate_signal
from btc_trading_bot.realtime import StreamEvent


def _technical(score: float) -> TechnicalAnalysis:
    now = datetime.now(timezone.utc)
    return TechnicalAnalysis(
        candle_time=now,
        close=100.0,
        ema20=101.0,
        ema50=99.0,
        ema_status="Bullish alignment",
        rsi14=60.0,
        rsi_status="Bullish momentum",
        macd=2.0,
        macd_signal=1.0,
        macd_histogram=1.0,
        macd_status="Bullish, strengthening",
        score=score,
    )


def _evaluation() -> Evaluation:
    now = datetime.now(timezone.utc)
    settings = Settings()
    technical = _technical(1.0)
    sentiment = SentimentAnalysis(score=0.0, label="Neutral")
    macro = MacroAnalysis(
        score=0.0,
        status="NO MAJOR ALERTS",
        risk_multiplier=1.0,
    )
    return Evaluation(
        market=MarketSnapshot(
            exchange="Test",
            symbol="BTC/USDT",
            price=100.0,
            change_24h=0.0,
            timestamp=now,
        ),
        technical=technical,
        sentiment=sentiment,
        macro=macro,
        signal=calculate_signal(technical, sentiment, macro, settings),
        evaluated_at=now,
        next_analysis_at=now + timedelta(hours=4),
    )


def test_independent_news_refresh_recalculates_signal() -> None:
    evaluation = _evaluation()
    updated_at = datetime.now(timezone.utc)

    refreshed = _apply_news_refresh(
        evaluation,
        SentimentAnalysis(score=1.0, label="Extremely Bullish"),
        MacroAnalysis(
            score=1.0,
            status="WATCHING MACRO",
            risk_multiplier=1.0,
        ),
        (),
        Settings(),
        updated_at,
    )

    assert refreshed.signal.signal == "STRONG BUY"
    assert refreshed.futures is not None
    assert refreshed.futures.action == "GO LONG"
    assert refreshed.news_updated_at == updated_at
    assert refreshed.news_health.status == "OK"
    assert refreshed.news_health.last_success_at == updated_at


def test_failed_news_refresh_preserves_last_analysis() -> None:
    evaluation = _evaluation()

    refreshed = _apply_news_refresh(
        evaluation,
        None,
        None,
        ("Feeds unavailable",),
        Settings(),
        datetime.now(timezone.utc),
    )

    assert refreshed.sentiment == evaluation.sentiment
    assert refreshed.macro == evaluation.macro
    assert "Feeds unavailable" in refreshed.errors
    assert refreshed.news_health.status == "FAILED"


def test_market_staleness_controls_rest_fallback() -> None:
    now = datetime.now(timezone.utc)
    fresh = MarketSnapshot(
        exchange="Test",
        symbol="BTC/USDT",
        price=100.0,
        change_24h=0.0,
        timestamp=now - timedelta(seconds=4),
    )
    stale = MarketSnapshot(
        exchange="Test",
        symbol="BTC/USDT",
        price=100.0,
        change_24h=0.0,
        timestamp=now - timedelta(seconds=20),
    )

    assert not _market_is_stale(fresh, now, stale_seconds=15)
    assert _market_is_stale(stale, now, stale_seconds=15)


def test_stream_events_attach_microstructure_analysis() -> None:
    now = datetime.now(timezone.utc)

    class Service:
        def apply_microstructure(self, kind, payload, received_at):
            assert kind == "trade"
            assert payload["p"] == "100"
            return "analysis"

    evaluation = _apply_stream_events(
        _evaluation(),
        Service(),
        [
            StreamEvent(
                kind="trade",
                received_at=now,
                payload={"p": "100", "q": "10", "m": False},
            )
        ],
    )

    assert evaluation.shakeout == "analysis"
    assert evaluation.stream_updated_at == now


def test_console_encoding_replaces_unsupported_characters(monkeypatch) -> None:
    configured: list[str] = []

    class Stream:
        def reconfigure(self, *, errors: str) -> None:
            configured.append(errors)

    monkeypatch.setattr("btc_trading_bot.app.sys.stdout", Stream())
    monkeypatch.setattr("btc_trading_bot.app.sys.stderr", Stream())

    _configure_console_encoding()

    assert configured == ["replace", "replace"]


def test_shakeout_event_log_path_reads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("BOT_SHAKEOUT_EVENT_LOG", "logs/shakeout.jsonl")
    monkeypatch.setenv("BOT_SHAKEOUT_BASELINE_WINDOW_SECONDS", "1200")
    monkeypatch.setenv("BOT_PROBABILITY_HORIZON_HOURS", "48")
    monkeypatch.setenv("BOT_PROBABILITY_MAX_SAMPLES", "80")
    monkeypatch.setenv("BOT_SIGNAL_JOURNAL_PATH", "logs/signals.jsonl")
    monkeypatch.setenv("BOT_PAPER_SETUP_JOURNAL_PATH", "logs/paper-setups.sqlite")
    monkeypatch.setenv("BOT_PAPER_SETUP_HORIZON_HOURS", "48")
    monkeypatch.setenv("BOT_HISTORY_DB_PATH", "data/history.sqlite")
    monkeypatch.setenv("BOT_SYMBOLS", " BTC/USDT,eth/usdt,BTC/USDT, SOL/USDT ")

    settings = Settings.from_env()

    assert settings.shakeout_event_log_path is not None
    assert settings.shakeout_event_log_path.name == "shakeout.jsonl"
    assert settings.shakeout_event_log_path.parent.name == "logs"
    assert settings.shakeout_baseline_window_seconds == 1200
    assert settings.probability_horizon_hours == 48
    assert settings.probability_max_samples == 80
    assert settings.signal_journal_path is not None
    assert settings.signal_journal_path.name == "signals.jsonl"
    assert settings.paper_setup_journal_path is not None
    assert settings.paper_setup_journal_path.name == "paper-setups.sqlite"
    assert settings.paper_setup_horizon_hours == 48
    assert settings.history_db_path is not None
    assert settings.history_db_path.name == "history.sqlite"
    assert settings.scanner_symbols == ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def test_default_scanner_symbols_include_major_futures_universe(monkeypatch) -> None:
    monkeypatch.delenv("BOT_SYMBOLS", raising=False)

    settings = Settings.from_env()

    assert "DOGE/USDT" in settings.scanner_symbols
    assert "SUI/USDT" in settings.scanner_symbols
    assert "BTC/USDT" in settings.scanner_symbols


def test_probability_backtest_falls_back_when_local_history_missing(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    live_candles = pd.DataFrame(
        [
            {
                "timestamp": start + timedelta(hours=4 * index),
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.5 + index,
                "volume": 1.0,
            }
            for index in range(80)
        ]
    )
    settings = Settings(
        history_db_path=tmp_path / "history.sqlite",
        probability_lookback_candles=80,
    )

    candles = _probability_candles_for_backtest(
        settings,
        "binanceusdm",
        "BTC/USDT:USDT",
        live_candles,
        horizon_candles=6,
    )

    assert candles is live_candles
