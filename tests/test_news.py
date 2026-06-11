import threading
from datetime import datetime, timezone

from btc_trading_bot.config import NewsFeed, Settings
from btc_trading_bot.models import Headline
from btc_trading_bot.news import NewsAnalyzer


def _headline(title: str, category: str = "crypto") -> Headline:
    return Headline(
        title=title,
        source="Test",
        url="https://example.com/story",
        published_at=datetime.now(timezone.utc),
        category=category,
    )


def test_bullish_bitcoin_headline_scores_positive() -> None:
    analyzer = NewsAnalyzer(Settings())
    try:
        result = analyzer.analyze_sentiment(
            [_headline("Bitcoin rally accelerates after ETF approval and record inflow")]
        )
    finally:
        analyzer.close()

    assert result.score > 0.2
    assert result.label in {"Bullish", "Extremely Bullish"}


def test_negative_macro_event_applies_defensive_multiplier() -> None:
    analyzer = NewsAnalyzer(Settings())
    try:
        result = analyzer.analyze_macro(
            [
                _headline(
                    "Federal Reserve turns hawkish as inflation surge raises rate hike risk",
                    category="macro",
                )
            ]
        )
    finally:
        analyzer.close()

    assert result.status in {"ELEVATED RISK", "HIGH RISK"}
    assert result.risk_multiplier < 1.0
    assert result.alerts


def test_feed_requests_run_concurrently(monkeypatch) -> None:
    feeds = (
        NewsFeed("First", "https://example.com/first", "crypto"),
        NewsFeed("Second", "https://example.com/second", "crypto"),
    )
    analyzer = NewsAnalyzer(Settings(feeds=feeds))
    barrier = threading.Barrier(2, timeout=1)

    def fetch_feed(feed: NewsFeed) -> list[Headline]:
        barrier.wait()
        return [_headline(f"Bitcoin update from {feed.name}")]

    monkeypatch.setattr(analyzer, "_fetch_feed", fetch_feed)

    headlines, errors = analyzer.fetch()

    assert len(headlines) == 2
    assert errors == ()
