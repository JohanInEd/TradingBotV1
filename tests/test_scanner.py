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


def _scan_stub(symbol: str, action: str, confidence: float, max_loss: float = 30.0):
    from datetime import timedelta

    from btc_trading_bot.models import (
        Evaluation,
        FuturesRecommendation,
        MarketSnapshot,
        SignalResult,
        TechnicalAnalysis,
    )
    from btc_trading_bot.scanner import _SymbolScan

    now = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    side = "LONG" if action == "GO LONG" else "SHORT" if action == "GO SHORT" else "FLAT"
    candidate = ScannerCandidate(
        symbol=symbol,
        action=action,
        side=side,
        confidence=confidence,
        price=100.0,
        change_24h=0.0,
        signal="STRONG BUY" if side == "LONG" else "STRONG SELL" if side == "SHORT" else "HOLD / NEUTRAL",
        score=confidence,
        raw_score=confidence,
        technical_score=confidence,
        sentiment_score=0.1,
        macro_score=0.0,
        market_regime="TRENDING UP",
        volatility_regime="NORMAL VOLATILITY",
        reason="test",
    )
    evaluation = None
    if side in {"LONG", "SHORT"}:
        technical = TechnicalAnalysis(
            candle_time=now,
            close=100.0,
            ema20=101.0,
            ema50=99.0,
            ema_status="Bullish alignment",
            rsi14=60.0,
            rsi_status="Bullish momentum",
            macd=2.0,
            macd_signal=1.0,
            macd_histogram=1.0,
            macd_status="Bullish, strengthening",
            score=confidence,
        )
        entry = 100.0
        stop = 98.5 if side == "LONG" else 101.5
        target = 103.0 if side == "LONG" else 97.0
        evaluation = Evaluation(
            market=MarketSnapshot(
                exchange="Test", symbol=symbol, price=100.0, change_24h=0.0, timestamp=now
            ),
            technical=technical,
            sentiment=SentimentAnalysis(score=0.1, label="Neutral"),
            macro=MacroAnalysis(score=0.0, status="NO MAJOR ALERTS", risk_multiplier=1.0),
            signal=SignalResult(
                signal=candidate.signal,
                raw_score=confidence,
                score=confidence,
                technical_contribution=confidence,
                sentiment_contribution=0.0,
                macro_contribution=0.0,
                risk_multiplier=1.0,
            ),
            futures=FuturesRecommendation(
                action=action,
                side=side,
                confidence=confidence,
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                quantity_btc=1.0,
                notional=100.0,
                max_loss=max_loss,
                leverage=1,
                reason="test",
            ),
            evaluated_at=now,
            next_analysis_at=now + timedelta(hours=4),
        )
    return _SymbolScan(
        candidate=candidate,
        evaluation=evaluation,
        exchange_id="binanceusdm",
        resolved_symbol=symbol,
    )


def test_scanner_allocation_respects_portfolio_and_records(tmp_path) -> None:
    from btc_trading_bot.paper_setups import PaperSetupJournal
    from btc_trading_bot.portfolio import empty_portfolio_state

    settings = Settings(
        scanner_symbols=("ETH/USDT", "SOL/USDT", "XRP/USDT"),
        portfolio_max_open_positions=2,
        portfolio_max_same_direction=1,
    )
    journal = PaperSetupJournal(tmp_path / "setups.sqlite")
    try:
        scanner = MarketScanner(settings, journal=journal)
        state = empty_portfolio_state(settings)
        scans = [
            _scan_stub("ETH/USDT:USDT", "GO LONG", 0.9),
            _scan_stub("SOL/USDT:USDT", "GO LONG", 0.8),
            _scan_stub("XRP/USDT:USDT", "GO SHORT", 0.7),
            _scan_stub("ADA/USDT:USDT", "STAY FLAT", 0.2),
            _scan_stub("BTC/USDT:USDT", "GO LONG", 0.95),
        ]

        candidates = scanner._apply_portfolio_allocation(
            scans, state, primary_symbol="BTC/USDT:USDT"
        )
    finally:
        journal.close()

    by_symbol = {candidate.symbol: candidate for candidate in candidates}
    assert by_symbol["ETH/USDT:USDT"].portfolio_status == "RECORDED"
    # Same-direction cap of one LONG blocks the second LONG.
    assert by_symbol["SOL/USDT:USDT"].portfolio_status.startswith("BLOCKED")
    assert by_symbol["XRP/USDT:USDT"].portfolio_status == "RECORDED"
    assert by_symbol["ADA/USDT:USDT"].portfolio_status is None
    assert by_symbol["BTC/USDT:USDT"].portfolio_status == "PRIMARY"

    with PaperSetupJournal(tmp_path / "setups.sqlite") as reopened:
        rows = reopened.load_setups()
    recorded_symbols = {row["symbol"] for row in rows}
    assert recorded_symbols == {"ETH/USDT:USDT", "XRP/USDT:USDT"}
