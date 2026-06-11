from datetime import datetime, timedelta, timezone

from btc_trading_bot.app import (
    _apply_news_refresh,
    _configure_console_encoding,
    _market_is_stale,
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


def test_console_encoding_replaces_unsupported_characters(monkeypatch) -> None:
    configured: list[str] = []

    class Stream:
        def reconfigure(self, *, errors: str) -> None:
            configured.append(errors)

    monkeypatch.setattr("btc_trading_bot.app.sys.stdout", Stream())
    monkeypatch.setattr("btc_trading_bot.app.sys.stderr", Stream())

    _configure_console_encoding()

    assert configured == ["replace", "replace"]
