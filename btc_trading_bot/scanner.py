from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import ExchangeClient
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.indicators import analyze_multi_timeframe
from btc_trading_bot.market_context import analyze_market_context
from btc_trading_bot.models import (
    MacroAnalysis,
    MarketScannerResult,
    ScannerCandidate,
    SentimentAnalysis,
)
from btc_trading_bot.strategy import calculate_signal


class MarketScanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(
        self,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
    ) -> MarketScannerResult | None:
        symbols = self.settings.scanner_symbols
        if not symbols:
            return None

        candidates: list[ScannerCandidate] = []
        errors: list[str] = []
        for symbol in symbols:
            try:
                candidates.append(self._scan_symbol(symbol, sentiment, macro))
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
                candidates.append(
                    ScannerCandidate(
                        symbol=symbol,
                        action="UNAVAILABLE",
                        side="ERROR",
                        confidence=0.0,
                        price=None,
                        change_24h=None,
                        signal="UNAVAILABLE",
                        score=0.0,
                        raw_score=0.0,
                        technical_score=0.0,
                        sentiment_score=sentiment.score,
                        macro_score=macro.score,
                        market_regime=None,
                        volatility_regime=None,
                        reason=str(exc),
                        error=str(exc),
                    )
                )

        ranked = sorted(candidates, key=_rank_key)
        return MarketScannerResult(
            symbols=symbols,
            candidates=tuple(ranked),
            generated_at=datetime.now(timezone.utc),
            errors=tuple(errors),
        )

    def _scan_symbol(
        self,
        symbol: str,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
    ) -> ScannerCandidate:
        settings = replace(self.settings, symbol=symbol)
        client = ExchangeClient(settings)
        try:
            market = client.fetch_market_snapshot()
            primary = client.fetch_closed_candles(settings.timeframe)
            daily = client.fetch_closed_candles(settings.daily_timeframe)
            hourly = client.fetch_closed_candles(settings.entry_timeframe)
            technical = analyze_multi_timeframe(
                primary,
                daily,
                hourly,
                primary_weight=settings.primary_timeframe_weight,
                daily_weight=settings.daily_timeframe_weight,
                hourly_weight=settings.entry_timeframe_weight,
            )
            signal = calculate_signal(technical, sentiment, macro, settings)
            futures = build_futures_recommendation(signal, market, settings)
            context = analyze_market_context(primary)
            return ScannerCandidate(
                symbol=client.symbol,
                action=futures.action,
                side=futures.side,
                confidence=futures.confidence,
                price=market.price,
                change_24h=market.change_24h,
                signal=signal.signal,
                score=signal.score,
                raw_score=signal.raw_score,
                technical_score=technical.score,
                sentiment_score=sentiment.score,
                macro_score=macro.score,
                market_regime=context.structure_regime,
                volatility_regime=context.volatility_regime,
                reason=_candidate_reason(futures.action, technical.score, sentiment, macro),
            )
        finally:
            client.close()


def _candidate_reason(
    action: str,
    technical_score: float,
    sentiment: SentimentAnalysis,
    macro: MacroAnalysis,
) -> str:
    if action == "GO LONG":
        direction = "bullish closed-candle confirmation"
    elif action == "GO SHORT":
        direction = "bearish closed-candle confirmation"
    else:
        direction = "no full multi-timeframe confirmation"
    return (
        f"{direction}; technical {technical_score:+.3f}, "
        f"sentiment {sentiment.score:+.3f} ({sentiment.label}), "
        f"macro {macro.status.lower()}"
    )


def _rank_key(candidate: ScannerCandidate) -> tuple[int, float]:
    if candidate.action in {"GO LONG", "GO SHORT"}:
        group = 0
    elif candidate.action == "STAY FLAT":
        group = 1
    else:
        group = 2
    return (group, -candidate.confidence)
