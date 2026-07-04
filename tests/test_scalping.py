from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    FuturesRecommendation,
    MarketSnapshot,
    PaperSetup,
    ShakeoutAnalysis,
    TradeFilterResult,
)
from btc_trading_bot.paper_setups import PaperSetupJournal
from btc_trading_bot.scalping import (
    SCALPING_TIMEFRAME,
    build_execution_cycle,
    evaluate_scalping,
    finalize_execution_cycle,
    scalping_settings,
    to_journal_evaluation,
)

EXCHANGE = "binanceusdm"
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
    # A decline followed by a sharp bounce: triggers a fresh EMA/MACD bullish
    # crossover (score +0.4125) without organically clearing the default
    # +-0.50 threshold, so it also exercises the STAY FLAT default path.
    decline = [60_000 - index * 5 for index in range(50)]
    bounce = [decline[-1] + index * 30 for index in range(1, 11)]
    return _candles(decline + bounce)


def _bearish_reversal_candles() -> pd.DataFrame:
    rally = [40_000 + index * 5 for index in range(50)]
    drop = [rally[-1] - index * 30 for index in range(1, 11)]
    return _candles(rally + drop)


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


def test_scalping_settings_is_purely_technical_and_tight_risk() -> None:
    settings = Settings(
        stop_loss_percent=0.015,
        reward_to_risk=2.0,
        risk_per_trade=0.005,
        paper_setup_horizon_hours=24,
        scalping_stop_loss_percent=0.003,
        scalping_reward_to_risk=1.5,
        scalping_risk_per_trade=0.0025,
        scalping_horizon_hours=2,
        scalping_buy_threshold=0.5,
        scalping_sell_threshold=-0.5,
    )

    mode = scalping_settings(settings)

    assert mode.technical_weight == 1.0
    assert mode.sentiment_weight == 0.0
    assert mode.macro_weight == 0.0
    assert mode.stop_loss_percent == pytest.approx(0.003)
    assert mode.reward_to_risk == pytest.approx(1.5)
    assert mode.risk_per_trade == pytest.approx(0.0025)
    assert mode.paper_setup_horizon_hours == 2
    assert mode.buy_threshold == pytest.approx(0.5)
    assert mode.sell_threshold == pytest.approx(-0.5)
    # The wider swing-trade settings are untouched.
    assert settings.stop_loss_percent == pytest.approx(0.015)


def test_bullish_reversal_stays_flat_under_default_threshold() -> None:
    result = evaluate_scalping(
        _bullish_reversal_candles(), _market(60_055.0), Settings()
    )

    assert result.futures.action == "STAY FLAT"
    assert result.paper_setup is None


def test_evaluate_scalping_builds_tight_long_setup_when_threshold_is_cleared() -> None:
    settings = replace(
        Settings(),
        scalping_buy_threshold=0.3,
        scalping_stop_loss_percent=0.003,
        scalping_reward_to_risk=1.5,
        # The bounce candles legitimately trip the "chasing the range
        # extreme" do-not-trade filter; disabled here to isolate the
        # setup-sizing behavior under test (the filter itself is covered
        # by tests/test_risk_filters.py).
        do_not_trade_filters_enabled=False,
    )

    result = evaluate_scalping(
        _bullish_reversal_candles(), _market(60_055.0), settings
    )

    assert result.futures.action == "GO LONG"
    assert result.futures.side == "LONG"
    assert result.paper_setup is not None
    setup = result.paper_setup
    stop_fraction = (setup.entry_price - setup.stop_loss) / setup.entry_price
    assert stop_fraction == pytest.approx(0.003, rel=1e-6)
    assert setup.reward_to_risk == pytest.approx(1.5, rel=1e-3)


def test_evaluate_scalping_builds_tight_short_setup_when_threshold_is_cleared() -> None:
    settings = replace(
        Settings(),
        scalping_sell_threshold=-0.3,
        scalping_stop_loss_percent=0.003,
        scalping_reward_to_risk=1.5,
        do_not_trade_filters_enabled=False,
    )

    result = evaluate_scalping(
        _bearish_reversal_candles(), _market(39_945.0), settings
    )

    assert result.futures.action == "GO SHORT"
    assert result.futures.side == "SHORT"
    assert result.paper_setup is not None
    setup = result.paper_setup
    stop_fraction = (setup.stop_loss - setup.entry_price) / setup.entry_price
    assert stop_fraction == pytest.approx(0.003, rel=1e-6)


def test_scalping_setup_round_trips_through_its_own_journal(tmp_path) -> None:
    settings = replace(
        Settings(), scalping_buy_threshold=0.3, do_not_trade_filters_enabled=False
    )
    result = evaluate_scalping(
        _bullish_reversal_candles(), _market(60_055.0), settings
    )
    assert result.paper_setup is not None

    evaluation = to_journal_evaluation(result, _market(60_055.0))
    with PaperSetupJournal(
        tmp_path / "scalping.sqlite", horizon_hours=settings.scalping_horizon_hours
    ) as journal:
        recorded = journal.record(
            evaluation,
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=SCALPING_TIMEFRAME,
            settings=scalping_settings(settings),
        )
        assert recorded
        assert journal.count_open(
            exchange=EXCHANGE, symbol=SYMBOL, timeframe=SCALPING_TIMEFRAME
        ) == 1

        rows = journal.load_setups()

    assert len(rows) == 1
    assert rows[0]["timeframe"] == SCALPING_TIMEFRAME
    assert rows[0]["side"] == "LONG"
    assert rows[0]["outcome"] == "OPEN"


def test_count_open_drops_after_resolution(tmp_path) -> None:
    settings = replace(
        Settings(), scalping_buy_threshold=0.3, do_not_trade_filters_enabled=False
    )
    candles = _bullish_reversal_candles()
    result = evaluate_scalping(candles, _market(60_055.0), settings)
    evaluation = to_journal_evaluation(result, _market(60_055.0))
    closed_at = result.technical.candle_time

    with PaperSetupJournal(
        tmp_path / "scalping.sqlite", horizon_hours=settings.scalping_horizon_hours
    ) as journal:
        journal.record(
            evaluation,
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=SCALPING_TIMEFRAME,
            settings=scalping_settings(settings),
        )
        assert journal.count_open(
            exchange=EXCHANGE, symbol=SYMBOL, timeframe=SCALPING_TIMEFRAME
        ) == 1

        entry = result.paper_setup.entry_price
        target = result.paper_setup.take_profit
        journal.resolve_with_candles(
            [
                {
                    "timestamp": closed_at + timedelta(minutes=5),
                    "high": max(entry, target) + 10,
                    "low": min(entry, target) - 10,
                    "close": target,
                }
            ],
            exchange=EXCHANGE,
            symbol=SYMBOL,
            timeframe=SCALPING_TIMEFRAME,
        )

        assert journal.count_open(
            exchange=EXCHANGE, symbol=SYMBOL, timeframe=SCALPING_TIMEFRAME
        ) == 0


def _futures(side: str, quantity_btc: float = 0.01) -> FuturesRecommendation:
    action = {"LONG": "GO LONG", "SHORT": "GO SHORT"}.get(side, "STAY FLAT")
    return FuturesRecommendation(
        action=action,
        side=side,
        confidence=0.6,
        entry_price=60_000.0 if side != "FLAT" else None,
        stop_loss=59_800.0 if side != "FLAT" else None,
        take_profit=60_300.0 if side != "FLAT" else None,
        quantity_btc=quantity_btc if side != "FLAT" else 0.0,
        notional=quantity_btc * 60_000.0 if side != "FLAT" else 0.0,
        max_loss=25.0 if side != "FLAT" else 0.0,
        leverage=1,
        reason="test",
    )


def _trade_filter(status: str, original_action: str, reasons: tuple = ()) -> TradeFilterResult:
    return TradeFilterResult(
        status=status,
        allowed=status in {"PASS", "DISABLED"},
        original_action=original_action,
        reasons=reasons,
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


def _paper_setup(side: str = "LONG") -> PaperSetup:
    now = datetime.now(timezone.utc)
    return PaperSetup(
        label="5m scalp setup",
        side=side,
        action="GO LONG" if side == "LONG" else "GO SHORT",
        status="OPEN",
        entry_price=60_000.0,
        stop_loss=59_800.0,
        take_profit=60_300.0,
        reward_to_risk=1.5,
        quantity_btc=0.01,
        notional=600.0,
        max_loss=2.0,
        leverage=1,
        position_estimate="0.0100 BTC (~$600.00)",
        signal_time=now,
        candle_time=now,
        close_price=60_000.0,
        technical_score=0.4,
        futures_action="GO LONG" if side == "LONG" else "GO SHORT",
    )


def test_build_execution_cycle_idle_when_no_directional_setup() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("NO SETUP", "STAY FLAT"),
        futures=_futures("FLAT"),
        shakeout=None,
        paper_setup=None,
    )

    assert cycle.status == "IDLE"
    assert [stage.status for stage in cycle.stages] == ["SKIPPED"] * 5


def test_build_execution_cycle_blocks_on_high_shakeout_risk() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("PASS", "GO LONG"),
        futures=_futures("LONG"),
        shakeout=_shakeout("HIGH", "DOWNSIDE"),
        paper_setup=_paper_setup("LONG"),
    )

    assert cycle.status == "BLOCKED"
    stages = {stage.name: stage.status for stage in cycle.stages}
    assert stages == {
        "Scam detect": "BLOCKED",
        "Validate": "SKIPPED",
        "Size": "SKIPPED",
        "Fill": "SKIPPED",
        "Settle": "SKIPPED",
    }


def test_build_execution_cycle_blocks_on_validate_failure() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("BLOCKED", "GO LONG", reasons=("ATR too high.",)),
        futures=_futures("FLAT"),
        shakeout=_shakeout("LOW"),
        paper_setup=None,
    )

    assert cycle.status == "BLOCKED"
    stages = {stage.name: stage for stage in cycle.stages}
    assert stages["Scam detect"].status == "PASS"
    assert stages["Validate"].status == "BLOCKED"
    assert "ATR too high." in stages["Validate"].detail
    assert stages["Size"].status == "SKIPPED"


def test_build_execution_cycle_pending_when_cleared_for_fill() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("PASS", "GO LONG"),
        futures=_futures("LONG"),
        shakeout=_shakeout("LOW"),
        paper_setup=_paper_setup("LONG"),
    )

    assert cycle.status == "PENDING"
    stages = {stage.name: stage.status for stage in cycle.stages}
    assert stages == {
        "Scam detect": "PASS",
        "Validate": "PASS",
        "Size": "PASS",
        "Fill": "PENDING",
        "Settle": "PENDING",
    }


def test_finalize_execution_cycle_marks_fill_and_settle_when_filled() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("PASS", "GO LONG"),
        futures=_futures("LONG"),
        shakeout=_shakeout("LOW"),
        paper_setup=_paper_setup("LONG"),
    )

    finalized = finalize_execution_cycle(
        cycle, filled=True, detail="Paper-filled LONG at $60,000.00."
    )

    assert finalized.status == "FILLED"
    stages = {stage.name: stage.status for stage in finalized.stages}
    assert stages["Fill"] == "PASS"
    assert stages["Settle"] == "PENDING"


def test_finalize_execution_cycle_skips_fill_when_already_open() -> None:
    cycle = build_execution_cycle(
        trade_filter=_trade_filter("PASS", "GO LONG"),
        futures=_futures("LONG"),
        shakeout=_shakeout("LOW"),
        paper_setup=_paper_setup("LONG"),
    )

    finalized = finalize_execution_cycle(
        cycle,
        filled=False,
        detail="A scalp paper setup for this symbol is already open.",
    )

    assert finalized.status == "SKIPPED"
    stages = {stage.name: stage.status for stage in finalized.stages}
    assert stages["Fill"] == "SKIPPED"
    assert stages["Settle"] == "SKIPPED"


def test_evaluate_scalping_wires_shakeout_into_execution_cycle() -> None:
    settings = replace(Settings(), scalping_buy_threshold=0.3)

    result = evaluate_scalping(
        _bullish_reversal_candles(),
        _market(60_055.0),
        settings,
        shakeout=_shakeout("HIGH", "DOWNSIDE"),
    )

    assert result.execution_cycle is not None
    assert result.execution_cycle.status == "BLOCKED"
    assert result.execution_cycle.stages[0].name == "Scam detect"
    assert result.execution_cycle.stages[0].status == "BLOCKED"
