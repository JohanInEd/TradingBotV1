from datetime import datetime, timezone

from btc_trading_bot.config import Settings
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
