from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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
    news_refresh_seconds: int = 600
    stream_stale_seconds: int = 15
    stream_retry_seconds: int = 3
    analysis_interval_hours: int = 4
    news_max_age_hours: int = 24
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
    paper_account_equity: float = 10_000.0
    risk_per_trade: float = 0.005
    stop_loss_percent: float = 0.015
    reward_to_risk: float = 2.0
    futures_leverage: int = 1
    max_position_fraction: float = 0.25
    price_range_horizon_hours: int = 24
    price_range_lookback_candles: int = 180
    shakeout_window_seconds: int = 300
    whale_trade_usd: float = 1_000_000.0
    shakeout_event_log_path: Path | None = None
    feeds: tuple[NewsFeed, ...] = field(default_factory=lambda: DEFAULT_FEEDS)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            symbol=os.getenv("BOT_SYMBOL", "BTC/USDT").upper(),
            exchange=os.getenv("BOT_EXCHANGE", "auto").lower(),
            market_refresh_seconds=_env_int("BOT_MARKET_REFRESH_SECONDS", 60, minimum=10),
            news_refresh_seconds=_env_int(
                "BOT_NEWS_REFRESH_SECONDS", 600, minimum=60
            ),
            stream_stale_seconds=_env_int(
                "BOT_STREAM_STALE_SECONDS", 15, minimum=5
            ),
            analysis_interval_hours=_env_int("BOT_ANALYSIS_INTERVAL_HOURS", 4, minimum=1),
            request_timeout_seconds=_env_float("BOT_HTTP_TIMEOUT_SECONDS", 12.0, minimum=1),
            headline_limit=_env_int("BOT_HEADLINE_LIMIT", 12, minimum=3),
            paper_account_equity=_env_float(
                "BOT_PAPER_ACCOUNT_EQUITY", 10_000.0, minimum=100.0
            ),
            risk_per_trade=_env_float(
                "BOT_RISK_PER_TRADE", 0.005, minimum=0.0001, maximum=0.02
            ),
            stop_loss_percent=_env_float(
                "BOT_STOP_LOSS_PERCENT", 0.015, minimum=0.001, maximum=0.10
            ),
            reward_to_risk=_env_float(
                "BOT_REWARD_TO_RISK", 2.0, minimum=1.0, maximum=5.0
            ),
            futures_leverage=_env_int(
                "BOT_FUTURES_LEVERAGE", 1, minimum=1, maximum=3
            ),
            max_position_fraction=_env_float(
                "BOT_MAX_POSITION_FRACTION", 0.25, minimum=0.01, maximum=1.0
            ),
            price_range_horizon_hours=_env_int(
                "BOT_PRICE_RANGE_HORIZON_HOURS", 24, minimum=4, maximum=168
            ),
            price_range_lookback_candles=_env_int(
                "BOT_PRICE_RANGE_LOOKBACK_CANDLES", 180, minimum=60, maximum=1000
            ),
            shakeout_window_seconds=_env_int(
                "BOT_SHAKEOUT_WINDOW_SECONDS", 300, minimum=60, maximum=1800
            ),
            whale_trade_usd=_env_float(
                "BOT_WHALE_TRADE_USD", 1_000_000.0, minimum=10_000.0
            ),
            shakeout_event_log_path=_env_path("BOT_SHAKEOUT_EVENT_LOG"),
        )


def _env_int(
    name: str, default: int, minimum: int, maximum: int | None = None
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = max(minimum, int(raw))
        return min(maximum, value) if maximum is not None else value
    except ValueError:
        return default


def _env_float(
    name: str,
    default: float,
    minimum: float,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = max(minimum, float(raw))
        return min(maximum, value) if maximum is not None else value
    except ValueError:
        return default


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()
