from dataclasses import replace
from datetime import datetime, timedelta, timezone

from btc_trading_bot.dashboard import (
    _futures_metrics_line,
    _refresh_health_line,
)
from btc_trading_bot.models import FuturesMetrics, RefreshHealth
from tests.test_app import _evaluation


def test_dashboard_shows_futures_metrics_and_refresh_health() -> None:
    now = datetime.now(timezone.utc)
    evaluation = replace(
        _evaluation(),
        futures_metrics=FuturesMetrics(
            mark_price=63_500.0,
            index_price=63_550.0,
            funding_rate=0.0001,
            next_funding_at=now + timedelta(hours=2),
            open_interest_amount=100_000.0,
            open_interest_value=6_350_000_000.0,
            long_short_ratio=1.65,
            updated_at=now,
        ),
        market_health=RefreshHealth(status="LIVE", last_success_at=now),
        futures_health=RefreshHealth(
            status="OK",
            last_success_at=now,
            next_refresh_at=now + timedelta(minutes=1),
        ),
        news_health=RefreshHealth(
            status="REFRESHING",
            last_success_at=now - timedelta(minutes=10),
        ),
    )

    metrics_text = _futures_metrics_line(evaluation).plain
    health_text = _refresh_health_line(evaluation).plain

    assert "Funding +0.0100%" in metrics_text
    assert "OI 100,000 BTC ($6.35B)" in metrics_text
    assert "L/S 1.65" in metrics_text
    assert "Market LIVE" in health_text
    assert "Futures OK" in health_text
    assert "News REFRESHING" in health_text
