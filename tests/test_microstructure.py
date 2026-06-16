from datetime import datetime, timedelta, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.microstructure import ShakeoutMonitor
from btc_trading_bot.models import FuturesMetrics


def test_shakeout_monitor_flags_downside_risk_from_sell_flow() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(
        Settings(whale_trade_usd=100_000.0, shakeout_window_seconds=300)
    )

    monitor.apply_depth(
        {
            "b": [["99", "1"], ["98", "1"]],
            "a": [["101", "12"], ["102", "10"]],
        },
        now,
    )
    monitor.apply_trade({"p": "100", "q": "2500", "m": True}, now)
    analysis = monitor.apply_liquidation(
        {"o": {"S": "SELL", "ap": "99", "z": "80"}},
        now,
    )

    assert analysis.status in {"MEDIUM", "HIGH"}
    assert analysis.direction == "DOWNSIDE SHAKEOUT RISK"
    assert analysis.large_trade_count == 1
    assert analysis.taker_sell_usd == 250_000.0
    assert "thin bid liquidity" in analysis.reason
    assert "long liquidation burst" in analysis.reason


def test_shakeout_monitor_uses_futures_crowding_and_oi_change() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(Settings())

    monitor.apply_futures_metrics(
        FuturesMetrics(
            mark_price=100.0,
            index_price=100.0,
            funding_rate=0.0,
            next_funding_at=None,
            open_interest_amount=1000.0,
            open_interest_value=100_000.0,
            long_short_ratio=1.8,
            updated_at=now,
        ),
        now,
    )
    analysis = monitor.apply_futures_metrics(
        FuturesMetrics(
            mark_price=100.0,
            index_price=100.0,
            funding_rate=0.0,
            next_funding_at=None,
            open_interest_amount=1025.0,
            open_interest_value=102_500.0,
            long_short_ratio=1.8,
            updated_at=now + timedelta(minutes=1),
        ),
        now + timedelta(minutes=1),
    )

    assert analysis.open_interest_change_percent == 2.5
    assert analysis.top_trader_long_short_ratio == 1.8
    assert "top traders crowded long" in analysis.reason
