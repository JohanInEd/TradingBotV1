from datetime import datetime, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    MacroAnalysis,
    MarketScannerResult,
    ScannerCandidate,
    SentimentAnalysis,
)
from btc_trading_bot.scanner import MarketScanner
from btc_trading_bot.web import _jsonable


def test_scanner_is_disabled_without_symbol_universe() -> None:
    result = MarketScanner(Settings()).scan(
        SentimentAnalysis(score=0.0, label="Neutral"),
        MacroAnalysis(score=0.0, status="NO MAJOR ALERTS", risk_multiplier=1.0),
    )

    assert result is None


def test_scanner_result_serializes_for_web_snapshot() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = MarketScannerResult(
        symbols=("BTC/USDT:USDT",),
        generated_at=now,
        candidates=(
            ScannerCandidate(
                symbol="BTC/USDT:USDT",
                action="GO LONG",
                side="LONG",
                confidence=0.72,
                price=100.0,
                change_24h=1.5,
                signal="STRONG BUY",
                score=0.72,
                raw_score=0.72,
                technical_score=1.0,
                sentiment_score=0.2,
                macro_score=0.0,
                market_regime="TRENDING UP",
                volatility_regime="NORMAL VOLATILITY",
                reason="bullish closed-candle confirmation",
            ),
        ),
    )

    payload = _jsonable(result)

    assert payload["generated_at"] == now.isoformat()
    assert payload["candidates"][0]["action"] == "GO LONG"
    assert payload["candidates"][0]["confidence"] == 0.72
