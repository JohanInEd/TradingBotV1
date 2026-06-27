from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.futures_simulator import (
    OUTCOME_TP,
    FuturesSimulatorSettings,
    format_simulation_report,
    simulate_futures,
    _simulate_trade,
)
from btc_trading_bot.futures import FuturesRecommendation
from btc_trading_bot.history import HistoryStore
from btc_trading_bot.models import (
    SignalResult,
    TechnicalAnalysis,
    TimeframeConfirmation,
)


def test_simulated_trade_charges_fees_and_funding() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = _candles(start, 2, 4, close=100.0)
    candles[1]["high"] = 102.5
    candles[1]["low"] = 99.5
    futures = FuturesRecommendation(
        action="GO LONG",
        side="LONG",
        confidence=1.0,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        quantity_btc=1.0,
        notional=100.0,
        max_loss=1.0,
        leverage=10,
        reason="test",
    )

    trade = _simulate_trade(
        "BTC/USDT:USDT",
        _frame(candles),
        0,
        futures,
        _technical(start, close=100.0, score=1.0),
        _signal(),
        FuturesSimulatorSettings(
            taker_fee_rate=0.001,
            funding_rate_8h=0.0001,
            maintenance_margin_rate=0.005,
        ),
    )

    assert trade.outcome == OUTCOME_TP
    assert trade.gross_pnl == pytest.approx(2.0)
    assert trade.fees == pytest.approx(0.202)
    assert trade.funding == pytest.approx(0.005)
    assert trade.net_pnl == pytest.approx(1.793)
    assert trade.net_r == pytest.approx(1.793)
    assert not trade.liquidation_at_risk


def test_futures_simulator_replays_history_store(monkeypatch, tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    settings = Settings(
        paper_account_equity=10_000.0,
        risk_per_trade=0.005,
        stop_loss_percent=0.01,
        reward_to_risk=2.0,
        futures_leverage=2,
        max_position_fraction=0.25,
    )

    def fake_analyze(primary, daily, hourly, **kwargs):
        current = primary.iloc[-1]
        candle_time = current["timestamp"].to_pydatetime()
        return _technical(candle_time, close=float(current["close"]), score=1.0)

    monkeypatch.setattr(
        "btc_trading_bot.futures_simulator.analyze_multi_timeframe",
        fake_analyze,
    )

    with HistoryStore(tmp_path / "history.sqlite") as store:
        store.upsert_candles(
            "binanceusdm",
            "SUI/USDT:USDT",
            "4h",
            _frame(_candles(start, 372, 4, close=100.0, high=103.0, low=99.5)),
        )
        store.upsert_candles(
            "binanceusdm",
            "SUI/USDT:USDT",
            "1h",
            _frame(_candles(start, 1488, 1, close=100.0, high=103.0, low=99.5)),
        )
        store.upsert_candles(
            "binanceusdm",
            "SUI/USDT:USDT",
            "1d",
            _frame(_candles(start, 62, 24, close=100.0)),
        )

        report = simulate_futures(
            store,
            exchange="binance-usdm",
            symbols=("SUI/USDT",),
            settings=settings,
            simulator_settings=FuturesSimulatorSettings(row_limit=2000),
        )

    result = report.results[0]
    output = format_simulation_report(report)

    assert result.symbol == "SUI/USDT:USDT"
    assert result.error is None
    assert result.stats.total_trades > 0
    assert result.stats.tp_count > 0
    assert result.stats.total_fees > 0
    assert "SUI/USDT:USDT" in output
    assert "maxDD=" in output


def _candles(
    start: datetime,
    count: int,
    hours: int,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        rows.append(
            {
                "timestamp": start + timedelta(hours=hours * index),
                "open": close,
                "high": high if high is not None else close + 0.5,
                "low": low if low is not None else close - 0.5,
                "close": close,
                "volume": 1000.0,
            }
        )
    return rows


def _frame(rows):
    import pandas as pd

    return pd.DataFrame(rows)


def _technical(
    candle_time: datetime,
    *,
    close: float,
    score: float,
) -> TechnicalAnalysis:
    return TechnicalAnalysis(
        candle_time=candle_time,
        close=close,
        ema20=101.0,
        ema50=100.0,
        ema_status="Bullish alignment",
        rsi14=60.0,
        rsi_status="Bullish momentum",
        macd=1.0,
        macd_signal=0.5,
        macd_histogram=0.5,
        macd_status="Bullish, strengthening",
        score=score,
        base_score=score,
        daily_trend=TimeframeConfirmation(
            candle_time=candle_time,
            close=close,
            status="Bullish alignment",
            score=score,
        ),
        hourly_entry=TimeframeConfirmation(
            candle_time=candle_time,
            close=close,
            status="Bullish entry timing",
            score=score,
        ),
    )


def _signal() -> SignalResult:
    return SignalResult(
        signal="STRONG BUY",
        raw_score=1.0,
        score=1.0,
        technical_contribution=1.0,
        sentiment_contribution=0.0,
        macro_contribution=0.0,
        risk_multiplier=1.0,
    )
