from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    exchange: str
    symbol: str
    price: float
    change_24h: float | None
    timestamp: datetime
    bid: float | None = None
    ask: float | None = None
    source: str = "REST"


@dataclass(frozen=True, slots=True)
class FuturesMetrics:
    mark_price: float | None
    index_price: float | None
    funding_rate: float | None
    next_funding_at: datetime | None
    open_interest_amount: float | None
    open_interest_value: float | None
    long_short_ratio: float | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshHealth:
    status: str = "STARTING"
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_refresh_at: datetime | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TimeframeConfirmation:
    candle_time: datetime
    close: float
    status: str
    score: float


@dataclass(frozen=True, slots=True)
class TechnicalAnalysis:
    candle_time: datetime
    close: float
    ema20: float
    ema50: float
    ema_status: str
    rsi14: float
    rsi_status: str
    macd: float
    macd_signal: float
    macd_histogram: float
    macd_status: str
    score: float
    base_score: float | None = None
    daily_trend: TimeframeConfirmation | None = None
    hourly_entry: TimeframeConfirmation | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


@dataclass(frozen=True, slots=True)
class Headline:
    title: str
    source: str
    url: str
    published_at: datetime
    category: str
    sentiment: float = 0.0


@dataclass(frozen=True, slots=True)
class SentimentAnalysis:
    score: float
    label: str
    headlines: tuple[Headline, ...] = ()


@dataclass(frozen=True, slots=True)
class MacroAnalysis:
    score: float
    status: str
    risk_multiplier: float
    alerts: tuple[Headline, ...] = ()


@dataclass(frozen=True, slots=True)
class SignalResult:
    signal: str
    raw_score: float
    score: float
    technical_contribution: float
    sentiment_contribution: float
    macro_contribution: float
    risk_multiplier: float


@dataclass(frozen=True, slots=True)
class FuturesRecommendation:
    action: str
    side: str
    confidence: float
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    quantity_btc: float
    notional: float
    max_loss: float
    leverage: int
    reason: str


@dataclass(frozen=True, slots=True)
class PaperSetup:
    label: str
    side: str
    action: str
    status: str
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_to_risk: float
    quantity_btc: float
    notional: float
    max_loss: float
    leverage: int
    position_estimate: str
    signal_time: datetime
    candle_time: datetime
    close_price: float
    technical_score: float
    futures_action: str
    market_regime: str | None = None
    volatility_regime: str | None = None
    trend_range_context: str | None = None
    probability_method: str | None = None
    outcome: str = "OPEN"
    disclaimer: str = "paper setup only; no order placed; not financial advice"


@dataclass(frozen=True, slots=True)
class PriceRangeForecast:
    horizon_hours: int
    expected_low: float
    expected_high: float
    support_level: float
    resistance_level: float
    downside_percent: float
    upside_percent: float
    confidence: str
    sample_size: int
    method: str
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ProbabilityForecast:
    horizon_hours: int
    up_probability: float
    down_probability: float
    flat_probability: float
    long_tp_before_sl_probability: float
    long_sl_before_tp_probability: float
    short_tp_before_sl_probability: float
    short_sl_before_tp_probability: float
    expected_long_r: float
    expected_short_r: float
    average_forward_return_percent: float
    sample_size: int
    candidate_count: int
    confidence: str
    method: str
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class MarketContext:
    volatility_regime: str
    structure_regime: str
    atr_percent: float
    realized_volatility_percent: float
    bollinger_width_percent: float
    range_position_percent: float
    trend_strength_percent: float
    reason: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MicrostructureStreamHealth:
    name: str
    status: str
    event_count: int
    last_event_at: datetime | None
    last_event_age_seconds: float | None


@dataclass(frozen=True, slots=True)
class ShakeoutAnalysis:
    status: str
    direction: str
    score: float
    order_book_imbalance: float | None
    bid_depth_usd: float | None
    ask_depth_usd: float | None
    taker_buy_usd: float
    taker_sell_usd: float
    large_trade_count: int
    large_trade_net_usd: float
    liquidation_buy_usd: float
    liquidation_sell_usd: float
    liquidation_count: int
    open_interest_change_percent: float | None
    top_trader_long_short_ratio: float | None
    reason: str
    updated_at: datetime | None = None
    depth_stress_ratio: float | None = None
    taker_flow_stress_ratio: float | None = None
    large_trade_stress_ratio: float | None = None
    liquidation_stress_ratio: float | None = None
    stream_health: tuple[MicrostructureStreamHealth, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Evaluation:
    market: MarketSnapshot
    technical: TechnicalAnalysis
    sentiment: SentimentAnalysis
    macro: MacroAnalysis
    signal: SignalResult
    evaluated_at: datetime
    next_analysis_at: datetime
    errors: tuple[str, ...] = field(default_factory=tuple)
    live_technical: TechnicalAnalysis | None = None
    news_updated_at: datetime | None = None
    stream_status: str = "REST"
    stream_updated_at: datetime | None = None
    futures: FuturesRecommendation | None = None
    paper_setup: PaperSetup | None = None
    futures_metrics: FuturesMetrics | None = None
    price_range: PriceRangeForecast | None = None
    probability_forecast: ProbabilityForecast | None = None
    market_context: MarketContext | None = None
    shakeout: ShakeoutAnalysis | None = None
    market_health: RefreshHealth = field(default_factory=RefreshHealth)
    futures_health: RefreshHealth = field(default_factory=RefreshHealth)
    news_health: RefreshHealth = field(default_factory=RefreshHealth)
