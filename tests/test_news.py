import threading
from datetime import datetime, timezone

from btc_trading_bot.config import NewsFeed, Settings
from btc_trading_bot.models import FuturesMetrics, Headline
from btc_trading_bot.news import (
    NewsAnalyzer,
    blend_derivatives_crowding,
    fear_greed_source_from_payload,
    gdelt_headlines_from_payload,
)


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
    assert result.sources
    assert result.sources[0].name == "Bitcoin headlines"


def test_fear_greed_source_maps_index_to_score() -> None:
    source = fear_greed_source_from_payload(
        {
            "data": [
                {
                    "value": "75",
                    "value_classification": "Greed",
                    "timestamp": "1781740800",
                }
            ]
        }
    )

    assert source.name == "Crypto Fear & Greed"
    assert source.score == 0.5
    assert source.label == "Greed"


def test_gdelt_payload_builds_crypto_and_macro_headlines() -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    headlines = gdelt_headlines_from_payload(
        {
            "articles": [
                {
                    "title": "Bitcoin ETF inflows rise before Fed decision",
                    "url": "https://example.com/btc",
                    "domain": "example.com",
                    "seendate": "20260618T110000Z",
                },
                {
                    "title": "Federal Reserve inflation warning rattles markets",
                    "url": "https://example.com/fed",
                    "domain": "macro.example",
                    "seendate": "20260618T103000Z",
                },
            ]
        },
        now=now,
        max_age_hours=24,
    )

    assert len(headlines) == 2
    assert headlines[0].category == "crypto"
    assert headlines[1].category == "macro"
    assert headlines[0].source == "GDELT: example.com"


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


def test_derivatives_crowding_blends_into_sentiment_sources() -> None:
    analyzer = NewsAnalyzer(Settings())
    try:
        sentiment = analyzer.analyze_sentiment(
            [_headline("Bitcoin holds steady as traders await volatility")]
        )
    finally:
        analyzer.close()
    metrics = FuturesMetrics(
        mark_price=100.0,
        index_price=100.0,
        funding_rate=0.0005,
        next_funding_at=None,
        open_interest_amount=10.0,
        open_interest_value=1000.0,
        long_short_ratio=2.0,
        updated_at=datetime.now(timezone.utc),
        crowding_score=1.0,
        crowding_label="Crowded Long",
        crowding_reason="funding +0.0500%, global L/S 2.00",
    )

    blended = blend_derivatives_crowding(sentiment, metrics)

    assert any(source.name == "Derivatives crowding" for source in blended.sources)
    assert blended.score > sentiment.score


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
    monkeypatch.setattr(analyzer, "_fetch_gdelt_headlines", lambda: [])

    headlines, errors = analyzer.fetch()

    assert len(headlines) == 2
    assert errors == ()
