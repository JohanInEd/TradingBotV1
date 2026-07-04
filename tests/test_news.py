import threading
from datetime import datetime, timezone

from btc_trading_bot.config import NewsFeed, Settings
from btc_trading_bot.models import FuturesMetrics, Headline
from btc_trading_bot.news import (
    NewsAnalyzer,
    blend_derivatives_crowding,
    classify_headline,
    fear_greed_source_from_payload,
    gdelt_headlines_from_payload,
    polymarket_source_from_payload,
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
    assert result.events
    assert result.headlines[0].event_type == "ETF flows"


def test_headline_classifier_tags_event_type_and_direction() -> None:
    classified = classify_headline(
        _headline("Bitcoin plunges as SEC crackdown sparks liquidation cascade")
    )

    assert classified.event_type == "SEC/regulation"
    assert classified.event_impact == "HIGH"
    assert classified.event_direction == "BEARISH"
    assert classified.event_confidence > 0.8


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


def test_polymarket_source_maps_directional_markets_to_sentiment() -> None:
    source = polymarket_source_from_payload(
        {
            "events": [
                {
                    "markets": [
                        {
                            "question": "Will Bitcoin be above $120,000 on July 31?",
                            "active": True,
                            "closed": False,
                            "outcomes": '["Yes","No"]',
                            "outcomePrices": '["0.70","0.30"]',
                            "volume24hr": 10000,
                        },
                        {
                            "question": "Will Bitcoin be below $90,000 on July 31?",
                            "active": True,
                            "closed": False,
                            "outcomes": '["Yes","No"]',
                            "outcomePrices": '["0.20","0.80"]',
                            "volume24hr": 8000,
                        },
                    ]
                }
            ]
        },
        now=datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert source.name == "Polymarket Bitcoin markets"
    assert source.score > 0
    assert "2 active directional markets" in source.detail


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
    assert result.events


def test_configured_economic_calendar_event_applies_event_risk(tmp_path) -> None:
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    path = tmp_path / "calendar.json"
    path.write_text(
        """
        {
          "events": [
            {
              "name": "FOMC rate decision",
              "event_type": "Fed/rates",
              "scheduled_at": "2026-06-18T14:00:00+00:00",
              "impact": "HIGH"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    analyzer = NewsAnalyzer(
        Settings(
            economic_calendar_path=path,
            economic_calendar_pre_event_window_hours=3,
            economic_calendar_post_event_window_hours=1,
        )
    )
    try:
        calendar = analyzer.analyze_economic_calendar(now)
        macro = analyzer.analyze_macro([], calendar=calendar)
    finally:
        analyzer.close()

    assert calendar is not None
    assert calendar.status == "HIGH EVENT RISK"
    assert calendar.risk_multiplier < 1.0
    assert calendar.active_events[0].name == "FOMC rate decision"
    assert macro.status == "HIGH EVENT RISK"
    assert macro.risk_multiplier == calendar.risk_multiplier


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


def test_tag_assets_matches_names_and_case_sensitive_tickers() -> None:
    from btc_trading_bot.news import tag_assets, tracked_assets

    assets = tracked_assets(Settings(scanner_symbols=("ETH/USDT", "SUI/USDT", "DOT/USDT")))

    assert tag_assets("Ethereum rallies as ETH funding turns positive", assets) == ("ETH",)
    assert tag_assets("Bitcoin and Solana lead the market higher", ("BTC", "SOL")) == ("BTC", "SOL")
    # Lowercase common words must not trigger short-ticker tags.
    assert tag_assets("Court hears sui generis lawsuit over polka dot art", assets) == ()
    assert tag_assets("SUI and DOT climb after upgrade", assets) == ("SUI", "DOT")


def test_analyze_sentiment_builds_asset_scores_and_asset_swap() -> None:
    from btc_trading_bot.news import sentiment_for_asset

    analyzer = NewsAnalyzer(Settings(scanner_symbols=("BTC/USDT", "ETH/USDT")))
    try:
        result = analyzer.analyze_sentiment(
            [
                _headline("Bitcoin plunges after ETF outflow shock"),
                _headline("Ethereum surges on record adoption rally"),
                _headline("Ethereum breakout accelerates as inflows rise"),
            ]
        )
    finally:
        analyzer.close()

    by_asset = {item.asset: item for item in result.asset_sentiment}
    assert by_asset["BTC"].headline_count == 1
    assert by_asset["ETH"].headline_count == 2
    assert by_asset["ETH"].score > 0 > by_asset["BTC"].score
    # Global score is driven by the BTC headline component.
    assert result.score < 0

    adjusted, applied = sentiment_for_asset(result, "ETH", min_headlines=2)
    assert applied is True
    assert adjusted.score > result.score
    news_source = next(s for s in adjusted.sources if s.name == "Bitcoin headlines")
    assert "ETH" in news_source.detail

    unchanged, applied_btc = sentiment_for_asset(result, "BTC")
    assert applied_btc is False
    assert unchanged is result
