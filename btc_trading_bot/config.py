from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NewsFeed:
    name: str
    url: str
    category: str


DEFAULT_FEEDS = (
    NewsFeed("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "crypto"),
    NewsFeed("Cointelegraph", "https://cointelegraph.com/rss", "crypto"),
    NewsFeed("Decrypt", "https://decrypt.co/feed", "crypto"),
    NewsFeed(
        "Google News Macro",
        (
            "https://news.google.com/rss/search?"
            "q=%28Federal+Reserve+OR+FOMC+OR+CPI+OR+inflation+OR+"
            "interest+rates+OR+central+bank%29+when%3A2d"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        "macro",
    ),
    NewsFeed(
        "Google News Crypto Risk",
        (
            "https://news.google.com/rss/search?"
            "q=%28bitcoin+OR+crypto%29+%28liquidation+OR+regulation+OR+ETF%29+when%3A2d"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        "macro",
    ),
)


@dataclass(frozen=True, slots=True)
class Settings:
    symbol: str = "BTC/USDT"
    timeframe: str = "4h"
    daily_timeframe: str = "1d"
    entry_timeframe: str = "1h"
    exchange: str = "auto"
    candle_limit: int = 250
    request_timeout_seconds: float = 12.0
    max_retries: int = 3
    market_refresh_seconds: int = 60
    news_refresh_seconds: int = 300
    stream_stale_seconds: int = 15
    stream_retry_seconds: int = 3
    analysis_interval_hours: int = 4
    news_max_age_hours: int = 48
    headline_limit: int = 12
    defensive_multiplier: float = 0.65
    buy_threshold: float = 0.65
    sell_threshold: float = -0.65
    technical_weight: float = 0.40
    sentiment_weight: float = 0.30
    macro_weight: float = 0.30
    primary_timeframe_weight: float = 0.60
    daily_timeframe_weight: float = 0.25
    entry_timeframe_weight: float = 0.15
    feeds: tuple[NewsFeed, ...] = field(default_factory=lambda: DEFAULT_FEEDS)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            symbol=os.getenv("BOT_SYMBOL", "BTC/USDT").upper(),
            exchange=os.getenv("BOT_EXCHANGE", "auto").lower(),
            market_refresh_seconds=_env_int("BOT_MARKET_REFRESH_SECONDS", 60, minimum=10),
            news_refresh_seconds=_env_int(
                "BOT_NEWS_REFRESH_SECONDS", 300, minimum=60
            ),
            stream_stale_seconds=_env_int(
                "BOT_STREAM_STALE_SECONDS", 15, minimum=5
            ),
            analysis_interval_hours=_env_int("BOT_ANALYSIS_INTERVAL_HOURS", 4, minimum=1),
            request_timeout_seconds=_env_float("BOT_HTTP_TIMEOUT_SECONDS", 12.0, minimum=1),
            headline_limit=_env_int("BOT_HEADLINE_LIMIT", 12, minimum=3),
        )


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default
