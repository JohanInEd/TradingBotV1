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

DEFAULT_SCANNER_SYMBOLS = (
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "LINK/USDT",
    "AVAX/USDT",
    "DOT/USDT",
    "SUI/USDT",
)


@dataclass(frozen=True, slots=True)
class Settings:
    symbol: str = "BTC/USDT"
    scanner_symbols: tuple[str, ...] = ()
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
    polymarket_sentiment_enabled: bool = False
    polymarket_search_query: str = "bitcoin"
    polymarket_market_limit: int = 12
    economic_calendar_enabled: bool = True
    economic_calendar_path: Path | None = None
    economic_calendar_lookahead_hours: int = 48
    economic_calendar_pre_event_window_hours: int = 6
    economic_calendar_post_event_window_hours: int = 2
    defensive_multiplier: float = 0.65
    adaptive_weights_enabled: bool = True
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
    futures_leverage: int = 5
    max_position_fraction: float = 0.25
    price_range_horizon_hours: int = 24
    price_range_lookback_candles: int = 180
    probability_horizon_hours: int = 24
    probability_lookback_candles: int = 220
    probability_min_samples: int = 30
    probability_max_samples: int = 120
    do_not_trade_filters_enabled: bool = True
    portfolio_risk_enabled: bool = True
    portfolio_max_open_positions: int = 4
    portfolio_max_same_direction: int = 3
    portfolio_max_open_risk_fraction: float = 0.02
    portfolio_symbol_cooldown_hours: float = 8.0
    portfolio_max_drawdown_percent: float = 15.0
    meta_model_enabled: bool = True
    meta_min_training_samples: int = 40
    meta_min_tp_probability: float = 0.45
    trade_filter_require_probability: bool = False
    trade_filter_min_probability_samples: int = 30
    trade_filter_min_expected_r: float = 0.0
    trade_filter_max_atr_percent: float = 3.0
    trade_filter_range_extreme_percent: float = 85.0
    trade_filter_funding_extreme: float = 0.0005
    trade_filter_long_short_extreme: float = 1.8
    shakeout_window_seconds: int = 300
    shakeout_baseline_window_seconds: int = 3600
    whale_trade_usd: float = 1_000_000.0
    shakeout_event_log_path: Path | None = None
    signal_journal_path: Path | None = None
    paper_setup_journal_path: Path | None = None
    paper_setup_horizon_hours: int = 24
    paper_ledger_fee_rate: float = 0.0004
    paper_ledger_slippage_bps: float = 2.0
    paper_ledger_funding_rate_8h: float = 0.0001
    history_db_path: Path | None = None
    scalping_enabled: bool = True
    scalping_refresh_seconds: int = 300
    scalping_buy_threshold: float = 0.50
    scalping_sell_threshold: float = -0.50
    scalping_stop_loss_percent: float = 0.003
    scalping_reward_to_risk: float = 1.5
    scalping_risk_per_trade: float = 0.0025
    scalping_horizon_hours: int = 2
    scalping_journal_path: Path | None = None
    active_trader_enabled: bool = True
    active_trader_equity: float = 100.0
    active_trader_margin_usd: float = 50.0
    active_trader_refresh_seconds: int = 1
    active_trader_risk_per_trade: float = 0.02
    active_trader_journal_path: Path | None = None
    active_trader_execution: str = "paper"
    active_trader_early_take_profit_mode: str = "positive_roi"
    active_trader_early_take_profit_min_roi_percent: float = 0.0
    active_trader_reentry_mode: str = "immediate"
    active_trader_flip_threshold: float = 0.50
    active_trader_cooldown_candles: int = 3
    active_trader_breakeven_progress_percent: float = 50.0
    active_trader_force_profit_progress_percent: float = 75.0
    binance_demo_api_key: str = ""
    binance_demo_api_secret: str = ""
    binance_demo_base_url: str = "https://demo-fapi.binance.com"
    binance_demo_recv_window_ms: int = 5000
    feeds: tuple[NewsFeed, ...] = field(default_factory=lambda: DEFAULT_FEEDS)

    @classmethod
    def from_env(cls) -> "Settings":
        exchange = os.getenv("BOT_EXCHANGE", "auto").lower()
        return cls(
            symbol=os.getenv("BOT_SYMBOL", "BTC/USDT").upper(),
            scanner_symbols=_env_symbols("BOT_SYMBOLS", DEFAULT_SCANNER_SYMBOLS),
            exchange=exchange,
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
            polymarket_sentiment_enabled=_env_bool(
                "BOT_POLYMARKET_SENTIMENT", False
            ),
            polymarket_search_query=os.getenv(
                "BOT_POLYMARKET_QUERY", "bitcoin"
            ).strip()
            or "bitcoin",
            polymarket_market_limit=_env_int(
                "BOT_POLYMARKET_MARKET_LIMIT", 12, minimum=1, maximum=50
            ),
            economic_calendar_enabled=_env_bool("BOT_ECONOMIC_CALENDAR", True),
            adaptive_weights_enabled=_env_bool("BOT_ADAPTIVE_WEIGHTS", True),
            economic_calendar_path=_env_path("BOT_ECONOMIC_CALENDAR_PATH"),
            economic_calendar_lookahead_hours=_env_int(
                "BOT_ECONOMIC_CALENDAR_LOOKAHEAD_HOURS",
                48,
                minimum=1,
                maximum=168,
            ),
            economic_calendar_pre_event_window_hours=_env_int(
                "BOT_ECONOMIC_CALENDAR_PRE_EVENT_HOURS",
                6,
                minimum=0,
                maximum=72,
            ),
            economic_calendar_post_event_window_hours=_env_int(
                "BOT_ECONOMIC_CALENDAR_POST_EVENT_HOURS",
                2,
                minimum=0,
                maximum=24,
            ),
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
                "BOT_FUTURES_LEVERAGE", 5, minimum=1, maximum=5
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
            probability_horizon_hours=_env_int(
                "BOT_PROBABILITY_HORIZON_HOURS", 24, minimum=4, maximum=168
            ),
            probability_lookback_candles=_env_int(
                "BOT_PROBABILITY_LOOKBACK_CANDLES", 220, minimum=80, maximum=1000
            ),
            probability_min_samples=_env_int(
                "BOT_PROBABILITY_MIN_SAMPLES", 30, minimum=5, maximum=500
            ),
            probability_max_samples=_env_int(
                "BOT_PROBABILITY_MAX_SAMPLES", 120, minimum=10, maximum=500
            ),
            do_not_trade_filters_enabled=_env_bool(
                "BOT_DO_NOT_TRADE_FILTERS", True
            ),
            portfolio_risk_enabled=_env_bool("BOT_PORTFOLIO_RISK", True),
            portfolio_max_open_positions=_env_int(
                "BOT_PORTFOLIO_MAX_OPEN_POSITIONS", 4, minimum=1, maximum=50
            ),
            portfolio_max_same_direction=_env_int(
                "BOT_PORTFOLIO_MAX_SAME_DIRECTION", 3, minimum=1, maximum=50
            ),
            portfolio_max_open_risk_fraction=_env_float(
                "BOT_PORTFOLIO_MAX_OPEN_RISK", 0.02, minimum=0.001, maximum=0.50
            ),
            portfolio_symbol_cooldown_hours=_env_float(
                "BOT_PORTFOLIO_COOLDOWN_HOURS", 8.0, minimum=0.0, maximum=168.0
            ),
            portfolio_max_drawdown_percent=_env_float(
                "BOT_PORTFOLIO_MAX_DRAWDOWN_PERCENT", 15.0, minimum=1.0, maximum=100.0
            ),
            meta_model_enabled=_env_bool("BOT_META_MODEL", True),
            meta_min_training_samples=_env_int(
                "BOT_META_MIN_TRAINING_SAMPLES", 40, minimum=10, maximum=5000
            ),
            meta_min_tp_probability=_env_float(
                "BOT_META_MIN_TP_PROBABILITY", 0.45, minimum=0.0, maximum=1.0
            ),
            trade_filter_require_probability=_env_bool(
                "BOT_TRADE_FILTER_REQUIRE_PROBABILITY", False
            ),
            trade_filter_min_probability_samples=_env_int(
                "BOT_TRADE_FILTER_MIN_PROBABILITY_SAMPLES",
                30,
                minimum=5,
                maximum=500,
            ),
            trade_filter_min_expected_r=_env_float(
                "BOT_TRADE_FILTER_MIN_EXPECTED_R", 0.0, minimum=-1.0, maximum=5.0
            ),
            trade_filter_max_atr_percent=_env_float(
                "BOT_TRADE_FILTER_MAX_ATR_PERCENT", 3.0, minimum=0.1, maximum=20.0
            ),
            trade_filter_range_extreme_percent=_env_float(
                "BOT_TRADE_FILTER_RANGE_EXTREME_PERCENT",
                85.0,
                minimum=50.0,
                maximum=99.0,
            ),
            trade_filter_funding_extreme=_env_float(
                "BOT_TRADE_FILTER_FUNDING_EXTREME",
                0.0005,
                minimum=0.0,
                maximum=0.01,
            ),
            trade_filter_long_short_extreme=_env_float(
                "BOT_TRADE_FILTER_LONG_SHORT_EXTREME",
                1.8,
                minimum=1.0,
                maximum=10.0,
            ),
            shakeout_window_seconds=_env_int(
                "BOT_SHAKEOUT_WINDOW_SECONDS", 300, minimum=60, maximum=1800
            ),
            shakeout_baseline_window_seconds=_env_int(
                "BOT_SHAKEOUT_BASELINE_WINDOW_SECONDS",
                3600,
                minimum=300,
                maximum=14_400,
            ),
            whale_trade_usd=_env_float(
                "BOT_WHALE_TRADE_USD", 1_000_000.0, minimum=10_000.0
            ),
            shakeout_event_log_path=_env_path("BOT_SHAKEOUT_EVENT_LOG"),
            signal_journal_path=_env_path("BOT_SIGNAL_JOURNAL_PATH"),
            paper_setup_journal_path=_env_path("BOT_PAPER_SETUP_JOURNAL_PATH"),
            paper_setup_horizon_hours=_env_int(
                "BOT_PAPER_SETUP_HORIZON_HOURS", 24, minimum=4, maximum=168
            ),
            paper_ledger_fee_rate=_env_float(
                "BOT_PAPER_LEDGER_FEE_RATE", 0.0004, minimum=0.0, maximum=0.01
            ),
            paper_ledger_slippage_bps=_env_float(
                "BOT_PAPER_LEDGER_SLIPPAGE_BPS", 2.0, minimum=0.0, maximum=100.0
            ),
            paper_ledger_funding_rate_8h=_env_float(
                "BOT_PAPER_LEDGER_FUNDING_RATE_8H",
                0.0001,
                minimum=-0.01,
                maximum=0.01,
            ),
            history_db_path=_env_path("BOT_HISTORY_DB_PATH"),
            scalping_enabled=_env_bool("BOT_SCALPING_ENABLED", True),
            scalping_refresh_seconds=_env_int(
                "BOT_SCALPING_REFRESH_SECONDS", 300, minimum=60, maximum=3600
            ),
            scalping_buy_threshold=_env_float(
                "BOT_SCALPING_BUY_THRESHOLD", 0.50, minimum=0.05, maximum=0.95
            ),
            scalping_sell_threshold=-_env_float(
                "BOT_SCALPING_SELL_THRESHOLD", 0.50, minimum=0.05, maximum=0.95
            ),
            scalping_stop_loss_percent=_env_float(
                "BOT_SCALPING_STOP_LOSS_PERCENT", 0.003, minimum=0.0005, maximum=0.05
            ),
            scalping_reward_to_risk=_env_float(
                "BOT_SCALPING_REWARD_TO_RISK", 1.5, minimum=1.0, maximum=5.0
            ),
            scalping_risk_per_trade=_env_float(
                "BOT_SCALPING_RISK_PER_TRADE", 0.0025, minimum=0.0001, maximum=0.02
            ),
            scalping_horizon_hours=_env_int(
                "BOT_SCALPING_HORIZON_HOURS", 2, minimum=1, maximum=24
            ),
            scalping_journal_path=_env_path("BOT_SCALPING_JOURNAL_PATH"),
            active_trader_enabled=_env_bool("BOT_ACTIVE_TRADER_ENABLED", True),
            active_trader_equity=_env_float(
                "BOT_ACTIVE_TRADER_EQUITY", 100.0, minimum=1.0
            ),
            active_trader_margin_usd=_env_float(
                "BOT_ACTIVE_TRADER_MARGIN_USD", 50.0, minimum=1.0
            ),
            active_trader_refresh_seconds=_env_int(
                "BOT_ACTIVE_TRADER_REFRESH_SECONDS", 1, minimum=1, maximum=3600
            ),
            active_trader_risk_per_trade=_env_float(
                "BOT_ACTIVE_TRADER_RISK_PER_TRADE", 0.02, minimum=0.0001, maximum=0.10
            ),
            active_trader_journal_path=(
                _env_path("BOT_ACTIVE_TRADER_JOURNAL_PATH")
                or Path("data/active-trader-fills.jsonl")
            ),
            active_trader_execution=_env_choice(
                "BOT_ACTIVE_TRADER_EXECUTION",
                "paper",
                {"paper", "binance_demo"},
            ),
            active_trader_early_take_profit_mode=_env_choice(
                "BOT_ACTIVE_TRADER_EARLY_TP_MODE",
                "positive_roi",
                {"disabled", "positive_roi", "min_roi", "progress"},
            ),
            active_trader_early_take_profit_min_roi_percent=_env_float(
                "BOT_ACTIVE_TRADER_EARLY_TP_MIN_ROI_PERCENT",
                0.0,
                minimum=0.0,
                maximum=100.0,
            ),
            active_trader_reentry_mode=_env_choice(
                "BOT_ACTIVE_TRADER_REENTRY_MODE",
                "immediate",
                {"immediate", "same_direction", "flip_on_reversal", "disabled_after_exit"},
            ),
            active_trader_flip_threshold=_env_float(
                "BOT_ACTIVE_TRADER_FLIP_THRESHOLD",
                0.50,
                minimum=0.01,
                maximum=1.0,
            ),
            active_trader_cooldown_candles=_env_int(
                "BOT_ACTIVE_TRADER_COOLDOWN_CANDLES",
                3,
                minimum=0,
                maximum=24,
            ),
            active_trader_breakeven_progress_percent=_env_float(
                "BOT_ACTIVE_TRADER_BREAKEVEN_PROGRESS_PERCENT",
                50.0,
                minimum=0.0,
                maximum=100.0,
            ),
            active_trader_force_profit_progress_percent=_env_float(
                "BOT_ACTIVE_TRADER_FORCE_PROFIT_PROGRESS_PERCENT",
                75.0,
                minimum=0.0,
                maximum=100.0,
            ),
            binance_demo_api_key=os.getenv("BOT_BINANCE_DEMO_API_KEY", "").strip(),
            binance_demo_api_secret=os.getenv("BOT_BINANCE_DEMO_API_SECRET", "").strip(),
            binance_demo_base_url=(
                os.getenv("BOT_BINANCE_DEMO_BASE_URL", "https://demo-fapi.binance.com")
                .strip()
                .rstrip("/")
                or "https://demo-fapi.binance.com"
            ),
            binance_demo_recv_window_ms=_env_int(
                "BOT_BINANCE_DEMO_RECV_WINDOW_MS",
                5000,
                minimum=1000,
                maximum=60000,
            ),
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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower().replace("-", "_")
    return value if value in choices else default


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser()


def _env_symbols(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    symbols: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        symbol = part.strip().upper()
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return tuple(symbols)
