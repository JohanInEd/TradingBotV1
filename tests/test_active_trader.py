from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from btc_trading_bot.active_trader import ACTIVE_TRADER_POSITION_SECONDS, ActiveTrader
from btc_trading_bot.binance_demo import BinanceDemoOrder
from btc_trading_bot.config import Settings
from btc_trading_bot.models import MarketSnapshot, ShakeoutAnalysis

SYMBOL = "BTC/USDT:USDT"


def _candles(closes: list[float], minutes: int = 5) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(minutes=minutes * index)
                for index in range(len(closes))
            ],
            "open": [close - 2 for close in closes],
            "high": [close + 4 for close in closes],
            "low": [close - 4 for close in closes],
            "close": closes,
            "volume": [10 + index for index in range(len(closes))],
        }
    )


def _bullish_reversal_candles() -> pd.DataFrame:
    decline = [60_000 - index * 5 for index in range(50)]
    bounce = [decline[-1] + index * 30 for index in range(1, 11)]
    return _candles(decline + bounce)


def _append_candle(
    frame: pd.DataFrame,
    *,
    high: float,
    low: float,
    close: float,
    minutes: int = 5,
) -> pd.DataFrame:
    last = frame["timestamp"].iloc[-1]
    row = {
        "timestamp": last + timedelta(minutes=minutes),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
    }
    return pd.concat([frame, pd.DataFrame([row])], ignore_index=True)


def _market(price: float) -> MarketSnapshot:
    return MarketSnapshot(
        exchange="Binance USD-M",
        symbol=SYMBOL,
        price=price,
        change_24h=0.5,
        timestamp=datetime.now(timezone.utc),
        bid=price - 1.0,
        ask=price + 1.0,
    )


def _shakeout(status: str = "LOW", direction: str = "NEUTRAL") -> ShakeoutAnalysis:
    return ShakeoutAnalysis(
        status=status,
        direction=direction,
        score=0.9 if status == "HIGH" else 0.1,
        order_book_imbalance=0.0,
        bid_depth_usd=1_000_000.0,
        ask_depth_usd=1_000_000.0,
        taker_buy_usd=0.0,
        taker_sell_usd=0.0,
        large_trade_count=0,
        large_trade_net_usd=0.0,
        liquidation_buy_usd=0.0,
        liquidation_sell_usd=0.0,
        liquidation_count=0,
        open_interest_change_percent=0.0,
        top_trader_long_short_ratio=1.0,
        reason="test",
    )


def _long_settings() -> Settings:
    return replace(
        Settings(),
        scalping_buy_threshold=0.3,
        do_not_trade_filters_enabled=False,
        active_trader_equity=100.0,
        active_trader_risk_per_trade=0.02,
    )


def test_active_trader_seeds_account_and_starts_active() -> None:
    trader = ActiveTrader(replace(Settings(), active_trader_equity=100.0))

    snapshot = trader.tick(_bullish_reversal_candles(), _market(60_055.0))

    assert snapshot.account.starting_equity == pytest.approx(100.0)
    assert snapshot.account.equity == pytest.approx(100.0)
    assert snapshot.account.open_position is not None
    assert snapshot.account.closed_trades == 0
    assert snapshot.account.win_rate is None
    assert snapshot.last_action.startswith("FILL ")
    assert snapshot.execution_cycle.status == "FILLED"
    assert snapshot.growth_curve[0]["outcome"] == "START"
    assert snapshot.growth_curve[0]["equity"] == pytest.approx(100.0)


def test_active_trader_fills_with_fixed_margin_and_leverage() -> None:
    trader = ActiveTrader(_long_settings())

    snapshot = trader.tick(
        _bullish_reversal_candles(), _market(60_055.0), shakeout=_shakeout("LOW")
    )

    assert snapshot.last_action == "FILL LONG"
    assert snapshot.execution_cycle.status == "FILLED"
    position = snapshot.account.open_position
    assert position is not None
    assert position.side == "LONG"
    assert position.notional == pytest.approx(250.0, rel=1e-6)
    assert snapshot.account.open_margin == pytest.approx(50.0, rel=1e-6)
    assert position.max_loss == pytest.approx(0.75, rel=1e-2)
    assert (position.expires_at - position.candle_time).total_seconds() == (
        ACTIVE_TRADER_POSITION_SECONDS
    )


def test_active_trader_mark_to_market_updates_open_roi_without_settling() -> None:
    settings = replace(_long_settings(), active_trader_early_take_profit_mode="disabled")
    trader = ActiveTrader(settings)
    opened = trader.tick(
        _bullish_reversal_candles(), _market(60_055.0), shakeout=_shakeout("LOW")
    )
    position = opened.account.open_position
    assert position is not None

    marked = trader.mark_to_market(_market(position.entry_price + 90.0))

    assert marked.account.open_position is not None
    assert marked.account.closed_trades == 0
    assert marked.account.unrealized_pnl > 0
    assert marked.account.unrealized_roi_percent > 0
    assert marked.account.open_margin == pytest.approx(
        position.notional / settings.futures_leverage
    )
    assert marked.account.open_total_return_percent > marked.account.return_percent
    assert marked.account.open_progress_percent > 0
    assert marked.account.mark_price == pytest.approx(position.entry_price + 90.0)


def test_active_trader_closes_live_profit_before_candle_completes() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    opened = trader.tick(
        _bullish_reversal_candles(), _market(60_055.0), shakeout=_shakeout("LOW")
    )
    position = opened.account.open_position
    assert position is not None

    marked = trader.mark_to_market(_market(position.entry_price + 90.0))

    assert marked.account.open_position is None
    assert marked.account.closed_trades == 1
    assert marked.account.wins == 1
    assert marked.recent_fills[-1].outcome == "TP"
    assert marked.recent_fills[-1].exit_reason == "EARLY_TP"
    assert marked.recent_fills[-1].net_pnl > 0
    assert marked.last_action == "LIVE TP"
    assert "before the 5-minute candle closed" in marked.last_detail
    assert marked.execution_cycle.status == "SETTLED"
    stages = {stage.name: stage.status for stage in marked.execution_cycle.stages}
    assert stages["Settle"] == "PASS"


def test_active_trader_take_profit_grows_equity() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    entry = trader._position.entry_price
    target = trader._position.take_profit

    tp_candles = _append_candle(
        base, high=target + 50.0, low=entry - 5.0, close=target + 20.0
    )
    snapshot = trader.tick(tp_candles, _market(target + 20.0), shakeout=_shakeout("LOW"))

    assert snapshot.account.closed_trades == 1
    assert snapshot.account.wins == 1
    assert snapshot.account.equity > 100.0
    assert snapshot.account.return_percent > 0.0
    assert snapshot.growth_curve[-1]["outcome"] == "TP"
    assert len(snapshot.growth_curve) == 2


def test_active_trader_takes_early_profit_and_opens_next_trade() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    position = trader._position
    assert position is not None
    entry = position.entry_price
    target = position.take_profit
    early_exit = entry + (target - entry) * 0.70

    profitable_candle = _append_candle(
        base,
        high=early_exit + 5.0,
        low=entry - 5.0,
        close=early_exit,
    )
    snapshot = trader.tick(
        profitable_candle, _market(early_exit), shakeout=_shakeout("LOW")
    )

    assert snapshot.account.closed_trades == 1
    assert snapshot.account.wins == 1
    assert snapshot.recent_fills[-1].outcome == "TP"
    assert snapshot.recent_fills[-1].exit_reason == "EARLY_TP"
    assert snapshot.recent_fills[-1].exit_price == pytest.approx(early_exit)
    assert snapshot.recent_fills[-1].net_pnl > 0
    assert snapshot.account.open_position is not None
    assert snapshot.last_action.startswith("FILL ")
    assert snapshot.growth_curve[-1]["outcome"] == "TP"
    assert snapshot.growth_curve[-1]["exit_reason"] == "EARLY_TP"


def test_active_trader_min_roi_can_leave_small_profit_as_expired() -> None:
    settings = replace(
        _long_settings(),
        active_trader_early_take_profit_mode="min_roi",
        active_trader_early_take_profit_min_roi_percent=5.0,
    )
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    position = trader._position
    assert position is not None
    entry = position.entry_price
    target = position.take_profit
    small_profit = entry + (target - entry) * 0.20

    profitable_candle = _append_candle(
        base,
        high=small_profit + 5.0,
        low=entry - 5.0,
        close=small_profit,
    )
    snapshot = trader.tick(
        profitable_candle, _market(small_profit), shakeout=_shakeout("LOW")
    )

    assert snapshot.recent_fills[-1].outcome == "EXPIRED"
    assert snapshot.recent_fills[-1].exit_reason == "EXPIRED"
    assert snapshot.account.wins == 0


def test_active_trader_can_disable_same_cycle_reentry_after_profit() -> None:
    settings = replace(
        _long_settings(),
        active_trader_reentry_mode="disabled_after_exit",
    )
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    position = trader._position
    assert position is not None
    entry = position.entry_price
    target = position.take_profit
    early_exit = entry + (target - entry) * 0.70

    profitable_candle = _append_candle(
        base,
        high=early_exit + 5.0,
        low=entry - 5.0,
        close=early_exit,
    )
    snapshot = trader.tick(
        profitable_candle, _market(early_exit), shakeout=_shakeout("LOW")
    )

    assert snapshot.recent_fills[-1].exit_reason == "EARLY_TP"
    assert snapshot.account.open_position is None
    assert snapshot.last_action == "REENTRY WAIT"


def test_active_trader_stop_loss_reduces_equity() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    stop = trader._position.stop_loss

    sl_candles = _append_candle(
        base, high=stop + 30.0, low=stop - 60.0, close=stop - 40.0
    )
    snapshot = trader.tick(sl_candles, _market(stop - 40.0), shakeout=_shakeout("LOW"))

    assert snapshot.account.closed_trades == 1
    assert snapshot.account.losses == 1
    assert snapshot.account.equity < 100.0
    assert snapshot.growth_curve[-1]["outcome"] == "SL"


def test_active_trader_expires_unresolved_position_on_next_cycle() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    entry = trader._position.entry_price

    next_candle = _append_candle(
        base, high=entry + 10.0, low=entry - 10.0, close=entry + 5.0
    )
    snapshot = trader.tick(
        next_candle, _market(entry + 5.0), shakeout=_shakeout("LOW")
    )

    assert snapshot.account.closed_trades == 1
    assert snapshot.recent_fills[-1].outcome == "EXPIRED"
    assert snapshot.growth_curve[-1]["outcome"] == "EXPIRED"
    assert snapshot.account.open_position is None
    assert snapshot.last_action == "COOLDOWN"
    assert snapshot.execution_cycle.status == "COOLDOWN"
    stages = {stage.name: stage.status for stage in snapshot.execution_cycle.stages}
    assert stages["Scam detect"] == "PASS"
    assert stages["Validate"] == "PASS"
    assert stages["Size"] == "PASS"
    assert stages["Fill"] == "COOLDOWN"
    assert snapshot.cooldown_detail


def test_active_trader_saves_open_and_settled_trade_events(tmp_path) -> None:
    journal_path = tmp_path / "active-trader.jsonl"
    settings = replace(_long_settings(), active_trader_journal_path=journal_path)
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    entry = trader._position.entry_price

    next_candle = _append_candle(
        base, high=entry + 10.0, low=entry - 10.0, close=entry + 5.0
    )
    trader.tick(next_candle, _market(entry + 5.0), shakeout=_shakeout("LOW"))

    rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["OPEN", "SETTLED"]
    assert rows[0]["side"] == "LONG"
    assert rows[1]["outcome"] == "EXPIRED"
    assert rows[1]["net_pnl"] == pytest.approx(trader._fills[-1].net_pnl)
    assert "equity_after" in rows[1]


def test_active_trader_cooldown_expires_after_configured_candles() -> None:
    settings = replace(_long_settings(), active_trader_cooldown_candles=1)
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    entry = trader._position.entry_price

    expired = _append_candle(
        base, high=entry + 10.0, low=entry - 10.0, close=entry + 5.0
    )
    blocked = trader.tick(expired, _market(entry + 5.0), shakeout=_shakeout("LOW"))
    assert blocked.last_action == "COOLDOWN"
    assert blocked.account.open_position is None

    released = _append_candle(
        expired,
        high=entry + 20.0,
        low=entry - 20.0,
        close=entry + 10.0,
    )
    snapshot = trader.tick(released, _market(entry + 10.0), shakeout=_shakeout("LOW"))

    assert snapshot.last_action.startswith("FILL ")
    assert snapshot.account.open_position is not None
    assert snapshot.cooldown_detail == ""


def test_active_trader_prepares_candidate_without_stacking_second_position() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)
    base = _bullish_reversal_candles()
    first = trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))
    assert first.account.open_position is not None
    original_entry = first.account.open_position.entry_price

    # Same candles: nothing new to settle, and a fresh directional signal is
    # prepared without opening a second position on top of the running one.
    second = trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))

    assert second.last_action == "PREPARED LONG"
    assert "while current LONG position is running" in second.last_detail
    assert second.account.closed_trades == 0
    assert second.account.open_position.entry_price == pytest.approx(original_entry)
    stages = {stage.name: stage.status for stage in second.execution_cycle.stages}
    assert stages["Fill"] == "SKIPPED"
    assert second.execution_cycle.status == "SKIPPED"


def test_active_trader_high_shakeout_blocks_the_cycle() -> None:
    settings = _long_settings()
    trader = ActiveTrader(settings)

    snapshot = trader.tick(
        _bullish_reversal_candles(),
        _market(60_055.0),
        shakeout=_shakeout("HIGH", "DOWNSIDE"),
    )

    assert snapshot.account.open_position is None
    assert snapshot.execution_cycle.status == "BLOCKED"
    assert snapshot.execution_cycle.stages[0].name == "Scam detect"
    assert snapshot.execution_cycle.stages[0].status == "BLOCKED"
    assert snapshot.scam_alert.startswith("Alert: scam/manipulation risk detected")
    assert snapshot.cycle_history[-1].scam_status == "BLOCKED"


class _DemoClient:
    def __init__(self) -> None:
        self.opens = []
        self.closes = []

    def open_market_position(self, **kwargs):
        self.opens.append(kwargs)
        return BinanceDemoOrder(
            symbol="BTCUSDT",
            side="BUY",
            order_id="open-1",
            client_order_id="client-open-1",
            status="NEW",
            raw={},
        )

    def close_market_position(self, **kwargs):
        self.closes.append(kwargs)
        return BinanceDemoOrder(
            symbol="BTCUSDT",
            side="SELL",
            order_id="close-1",
            client_order_id="client-close-1",
            status="NEW",
            raw={},
        )


def test_active_trader_binance_demo_places_open_and_close_orders() -> None:
    demo = _DemoClient()
    settings = replace(
        _long_settings(),
        active_trader_execution="binance_demo",
    )
    trader = ActiveTrader(settings, demo_client=demo)
    base = _bullish_reversal_candles()
    opened = trader.tick(base, _market(60_055.0), shakeout=_shakeout("LOW"))

    position = opened.account.open_position
    assert position is not None
    assert position.execution_mode == "binance_demo"
    assert position.open_order_id == "open-1"
    assert opened.execution_mode == "binance_demo"
    assert "Binance Demo" in opened.last_detail
    assert demo.opens[-1]["side"] == "LONG"

    entry = position.entry_price
    target = position.take_profit
    tp_candles = _append_candle(
        base, high=target + 50.0, low=entry - 5.0, close=target + 20.0
    )
    settled = trader.tick(tp_candles, _market(target + 20.0), shakeout=_shakeout("LOW"))

    assert demo.closes[-1]["side"] == "LONG"
    assert settled.recent_fills[-1].execution_mode == "binance_demo"
    assert settled.recent_fills[-1].close_order_id == "close-1"


def test_active_trader_binance_demo_without_keys_does_not_open_local_position() -> None:
    settings = replace(
        _long_settings(),
        active_trader_execution="binance_demo",
    )
    trader = ActiveTrader(settings)

    snapshot = trader.tick(
        _bullish_reversal_candles(),
        _market(60_055.0),
        shakeout=_shakeout("LOW"),
    )

    assert snapshot.account.open_position is None
    assert snapshot.last_action == "DEMO NOT READY"
    assert snapshot.execution_cycle.status == "SKIPPED"
    assert "BOT_BINANCE_DEMO_API_KEY" in snapshot.last_detail
