from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.config import Settings
from btc_trading_bot.futures_simulator import FuturesSimulatorSettings, SimulatedTrade
from btc_trading_bot.walkforward import (
    ParameterSet,
    format_walk_forward_report,
    run_walk_forward,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
DAYS = 150


def _trade(entry_time: datetime, net_r: float) -> SimulatedTrade:
    outcome = "TP" if net_r > 0 else "SL"
    return SimulatedTrade(
        symbol="BTC/USDT:USDT",
        side="LONG",
        outcome=outcome,
        entry_time=entry_time,
        exit_time=entry_time + timedelta(hours=8),
        duration_hours=8.0,
        entry_price=100.0,
        exit_price=100.0 + net_r,
        stop_loss=99.0,
        take_profit=102.0,
        liquidation_price=None,
        liquidation_distance_percent=None,
        liquidation_at_risk=False,
        liquidation_touched=False,
        quantity=1.0,
        notional=100.0,
        initial_margin=100.0,
        max_loss=50.0,
        leverage=1,
        signal_score=0.7,
        technical_score=0.7,
        gross_pnl=net_r * 50.0,
        fees=0.0,
        funding=0.0,
        net_pnl=net_r * 50.0,
        gross_r=net_r,
        net_r=net_r,
    )


def test_walk_forward_selects_on_train_and_scores_out_of_sample(monkeypatch) -> None:
    aggressive = ParameterSet(0.55, 0.010, 1.5)
    settings = Settings()  # baseline: threshold 0.65, stop 0.015, rr 2.0
    simulator_settings = FuturesSimulatorSettings(entry_threshold=0.65)

    def fake_simulate(symbol, primary, daily, hourly, sim_settings, simulator_config):
        trades = []
        for day in range(DAYS):
            entry = START + timedelta(days=day)
            if abs(simulator_config.entry_threshold - 0.55) < 1e-9:
                # Aggressive params look great early, then break down in the
                # final six weeks -- the classic overfitting trap.
                net_r = 2.0 if day < DAYS - 42 else -1.0
            else:
                net_r = 0.5
            trades.append(_trade(entry, net_r))
        return tuple(trades)

    monkeypatch.setattr(
        "btc_trading_bot.walkforward._simulate_symbol_trades", fake_simulate
    )

    def provider(symbol: str):
        primary = pd.DataFrame(
            {"timestamp": [START + timedelta(days=day) for day in range(DAYS)]}
        )
        return primary, primary, primary

    report = run_walk_forward(
        provider,
        exchange="binanceusdm",
        symbols=("BTC/USDT:USDT",),
        settings=settings,
        simulator_settings=simulator_settings,
        grid=[aggressive],
        folds=2,
        test_days=21,
        train_days=60,
        min_train_trades=8,
    )

    assert len(report.folds) == 2
    # Train windows are dominated by the aggressive params' +2R streak.
    assert all(fold.chosen == aggressive for fold in report.folds)
    assert all(
        fold.train.net_r is not None and fold.train.net_r > 0.5
        for fold in report.folds
    )
    # Out of sample the aggressive params collapse while baseline holds.
    assert report.oos.net_r is not None and report.oos.net_r < 0
    assert report.baseline_oos.net_r is not None
    assert abs(report.baseline_oos.net_r - 0.5) < 1e-9
    assert report.oos.trades > 0
    assert report.grid_size == 2  # aggressive + deduplicated baseline

    text = format_walk_forward_report(report)
    assert "Pooled out-of-sample" in text
    assert "threshold=0.55" in text


def test_walk_forward_requires_history(monkeypatch) -> None:
    import pytest

    from btc_trading_bot.walkforward import WalkForwardError

    def empty_provider(symbol: str):
        raise ValueError("no rows")

    with pytest.raises(WalkForwardError):
        run_walk_forward(
            empty_provider,
            exchange="binanceusdm",
            symbols=("BTC/USDT:USDT",),
            settings=Settings(),
            simulator_settings=FuturesSimulatorSettings(),
            grid=[],
            folds=2,
        )
