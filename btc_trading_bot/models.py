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
    top_trader_long_short_ratio: float | None = None
    top_trader_position_ratio: float | None = None
    taker_buy_sell_ratio: float | None = None
    taker_buy_volume: float | None = None
    taker_sell_volume: float | None = None
    crowding_score: float | None = None
    crowding_label: str | None = None
    crowding_reason: str | None = None


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
    event_type: str = "general"
    event_impact: str = "LOW"
    event_direction: str = "NEUTRAL"
    event_confidence: float = 0.0
    assets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NewsEventSummary:
    event_type: str
    count: int
    average_sentiment: float
    impact: str
    direction: str
    latest_at: datetime | None = None
    representative_title: str | None = None


@dataclass(frozen=True, slots=True)
class EconomicCalendarEvent:
    name: str
    event_type: str
    scheduled_at: datetime
    impact: str
    source: str = "built-in"


@dataclass(frozen=True, slots=True)
class EconomicCalendarRisk:
    status: str
    risk_multiplier: float
    active_events: tuple[EconomicCalendarEvent, ...] = ()
    upcoming_events: tuple[EconomicCalendarEvent, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SentimentSource:
    name: str
    score: float
    label: str
    detail: str
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AssetSentiment:
    asset: str
    score: float
    label: str
    headline_count: int
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SentimentAnalysis:
    score: float
    label: str
    headlines: tuple[Headline, ...] = ()
    sources: tuple[SentimentSource, ...] = ()
    events: tuple[NewsEventSummary, ...] = ()
    asset_sentiment: tuple[AssetSentiment, ...] = ()


@dataclass(frozen=True, slots=True)
class MacroAnalysis:
    score: float
    status: str
    risk_multiplier: float
    alerts: tuple[Headline, ...] = ()
    events: tuple[NewsEventSummary, ...] = ()
    calendar: EconomicCalendarRisk | None = None


@dataclass(frozen=True, slots=True)
class MetaModelAssessment:
    status: str
    trained: bool
    sample_count: int
    tp_probability: float | None
    threshold: float
    detail: str


@dataclass(frozen=True, slots=True)
class SignalProfile:
    name: str
    reason: str
    buy_threshold: float
    sell_threshold: float
    primary_weight: float
    daily_weight: float
    hourly_weight: float
    adaptive: bool = False


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
class TradeFilterResult:
    status: str
    allowed: bool
    original_action: str
    reasons: tuple[str, ...] = ()


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
class PortfolioState:
    open_positions: int
    long_positions: int
    short_positions: int
    open_risk_usd: float
    equity: float
    peak_equity: float
    current_drawdown_percent: float
    kill_switch_active: bool
    generated_at: datetime
    open_symbols: tuple[str, ...] = ()
    cooldowns: tuple[tuple[str, datetime], ...] = ()
    open_setup_keys: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioDecision:
    allowed: bool
    status: str
    reasons: tuple[str, ...] = ()
    state: PortfolioState | None = None


@dataclass(frozen=True, slots=True)
class ScannerCandidate:
    symbol: str
    action: str
    side: str
    confidence: float
    price: float | None
    change_24h: float | None
    signal: str
    score: float
    raw_score: float
    technical_score: float
    sentiment_score: float
    macro_score: float
    market_regime: str | None
    volatility_regime: str | None
    reason: str
    error: str | None = None
    sentiment_basis: str = "global"
    portfolio_status: str | None = None


@dataclass(frozen=True, slots=True)
class MarketScannerResult:
    symbols: tuple[str, ...]
    candidates: tuple[ScannerCandidate, ...]
    generated_at: datetime
    errors: tuple[str, ...] = ()
    portfolio: PortfolioState | None = None


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
class ScenarioPathPoint:
    time: datetime
    price: float
    percent_change: float


@dataclass(frozen=True, slots=True)
class ScenarioForecast:
    horizon_hours: int
    sample_size: int
    candidate_count: int
    confidence: str
    method: str
    generated_at: datetime
    up_probability: float
    down_probability: float
    median_path: tuple[ScenarioPathPoint, ...]
    lower_band_path: tuple[ScenarioPathPoint, ...]
    upper_band_path: tuple[ScenarioPathPoint, ...]
    expected_low: float
    expected_high: float


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
class ExecutionStage:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ExecutionCycle:
    status: str
    stages: tuple[ExecutionStage, ...]


@dataclass(frozen=True, slots=True)
class ActiveTraderCyclePoint:
    recorded_at: datetime
    status: str
    side: str
    action: str
    technical_score: float
    scam_status: str
    validate_status: str
    size_status: str
    fill_status: str
    settle_status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ScalpingEvaluation:
    technical: TechnicalAnalysis
    market_context: MarketContext | None
    signal: SignalResult
    futures: FuturesRecommendation
    trade_filter: TradeFilterResult | None
    paper_setup: PaperSetup | None
    evaluated_at: datetime
    execution_cycle: ExecutionCycle | None = None


@dataclass(frozen=True, slots=True)
class ActiveTradePosition:
    """A single open paper position held by the active trader."""

    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity_btc: float
    notional: float
    max_loss: float
    reward_to_risk: float
    opened_at: datetime
    candle_time: datetime
    expires_at: datetime
    original_stop_loss: float | None = None
    protected_stop_loss: float | None = None
    execution_mode: str = "paper"
    open_order_id: str | None = None
    open_order_status: str | None = None
    open_order_error: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveTradeFill:
    """A closed paper trade with the reason the active trader used to exit."""

    side: str
    outcome: str
    entry_price: float
    exit_price: float
    quantity_btc: float
    gross_pnl: float
    fees: float
    net_pnl: float
    net_r: float
    opened_at: datetime
    closed_at: datetime
    exit_reason: str = ""
    roi_percent: float = 0.0
    execution_mode: str = "paper"
    close_order_id: str | None = None
    close_order_status: str | None = None
    close_order_error: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveTraderAccount:
    """Rolling state of the fixed-size active-trading paper account."""

    starting_equity: float
    equity: float
    realized_pnl: float
    return_percent: float
    peak_equity: float
    max_drawdown_percent: float
    closed_trades: int
    wins: int
    losses: int
    win_rate: float | None
    open_position: ActiveTradePosition | None
    unrealized_pnl: float = 0.0
    unrealized_roi_percent: float = 0.0
    open_margin: float = 0.0
    open_total_pnl: float = 0.0
    open_total_return_percent: float = 0.0
    open_progress_percent: float = 0.0
    open_distance_to_stop_percent: float | None = None
    open_distance_to_target_percent: float | None = None
    mark_price: float | None = None


@dataclass(frozen=True, slots=True)
class ActiveTraderSnapshot:
    """Immutable per-tick view of the active trader for the dashboard."""

    enabled: bool
    symbol: str
    interval_seconds: int
    evaluated_at: datetime
    account: ActiveTraderAccount
    execution_cycle: ExecutionCycle | None = None
    technical: TechnicalAnalysis | None = None
    signal: SignalResult | None = None
    futures: FuturesRecommendation | None = None
    growth_curve: tuple[dict[str, float | str | None], ...] = ()
    recent_fills: tuple[ActiveTradeFill, ...] = ()
    cycle_history: tuple[ActiveTraderCyclePoint, ...] = ()
    last_action: str = "IDLE"
    last_detail: str = ""
    execution_mode: str = "paper"
    execution_status: str = "paper simulation"
    cooldown_detail: str = ""
    scam_alert: str = ""
    disclaimer: str = (
        "paper only; no order placed; not financial advice; session simulation"
    )


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
    trade_filter: TradeFilterResult | None = None
    paper_setup: PaperSetup | None = None
    futures_metrics: FuturesMetrics | None = None
    price_range: PriceRangeForecast | None = None
    probability_forecast: ProbabilityForecast | None = None
    scenario_forecast: ScenarioForecast | None = None
    market_context: MarketContext | None = None
    shakeout: ShakeoutAnalysis | None = None
    market_health: RefreshHealth = field(default_factory=RefreshHealth)
    futures_health: RefreshHealth = field(default_factory=RefreshHealth)
    news_health: RefreshHealth = field(default_factory=RefreshHealth)
    scanner: MarketScannerResult | None = None
    portfolio: PortfolioDecision | None = None
    signal_profile: SignalProfile | None = None
    meta: MetaModelAssessment | None = None
    scalping: ScalpingEvaluation | None = None
    active_trader: ActiveTraderSnapshot | None = None
