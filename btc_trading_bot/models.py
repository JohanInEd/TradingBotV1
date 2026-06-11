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
