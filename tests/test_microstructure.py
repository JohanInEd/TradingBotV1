import json
from datetime import datetime, timedelta, timezone

from btc_trading_bot.config import Settings
from btc_trading_bot.microstructure import (
    ShakeoutEventRecorder,
    ShakeoutMonitor,
    replay_shakeout_event_comparison,
    replay_shakeout_events,
)
from btc_trading_bot.models import FuturesMetrics
from btc_trading_bot.shakeout_backtest import summarize


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


def test_shakeout_monitor_ignores_tiny_one_sided_trade_noise() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(Settings(whale_trade_usd=1_000_000.0))

    analysis = monitor.apply_trade({"p": "100", "q": "10", "m": True}, now)

    assert analysis.status == "CALM"
    assert "aggressive sell flow" not in analysis.reason


def test_shakeout_monitor_normalizes_depth_and_flow_against_baselines() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(
        Settings(
            whale_trade_usd=500_000.0,
            shakeout_window_seconds=300,
            shakeout_baseline_window_seconds=900,
        )
    )

    for index in range(6):
        timestamp = now + timedelta(seconds=index * 30)
        monitor.apply_depth(
            {
                "b": [["100", "10"]],
                "a": [["101", "10"]],
            },
            timestamp,
        )
        monitor.apply_trade(
            {"p": "100", "q": "100", "m": index % 2 == 0},
            timestamp,
        )

    analysis = monitor.apply_trade(
        {"p": "100", "q": "2500", "m": True},
        now + timedelta(minutes=4),
    )
    analysis = monitor.apply_depth(
        {
            "b": [["100", "2"]],
            "a": [["101", "10"]],
        },
        now + timedelta(minutes=4, seconds=1),
    )

    assert analysis.depth_stress_ratio is not None
    assert analysis.depth_stress_ratio > 1.0
    assert analysis.taker_flow_stress_ratio is not None
    assert analysis.taker_flow_stress_ratio > 1.0
    assert "baseline" in analysis.reason


def test_shakeout_monitor_decays_old_stress_smoothly() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(
        Settings(whale_trade_usd=100_000.0, shakeout_window_seconds=300)
    )

    peak = monitor.apply_trade({"p": "100", "q": "5000", "m": True}, now)
    faded = monitor.analyze(now + timedelta(seconds=301))
    gone = monitor.analyze(now + timedelta(seconds=1200))

    assert 0 < faded.taker_sell_usd < peak.taker_sell_usd
    assert faded.score > 0
    assert faded.score < peak.score
    assert gone.status == "CALM"


def test_shakeout_monitor_reports_stream_health_by_microstructure_feed() -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    monitor = ShakeoutMonitor(Settings(stream_stale_seconds=15))

    monitor.apply_depth({"b": [["100", "1"]], "a": [["101", "1"]]}, now)
    analysis = monitor.apply_trade(
        {"p": "100", "q": "10", "m": False},
        now + timedelta(seconds=1),
    )

    health = {stream.name: stream for stream in analysis.stream_health}
    assert health["depth"].event_count == 1
    assert health["aggTrade"].event_count == 1
    assert health["forceOrder"].status == "WAITING"

    stale = monitor.analyze(now + timedelta(seconds=20))
    stale_health = {stream.name: stream for stream in stale.stream_health}
    assert stale_health["depth"].status == "STALE"
    assert stale_health["aggTrade"].status == "STALE"


def test_shakeout_events_can_be_recorded_and_replayed(tmp_path) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    settings = Settings(whale_trade_usd=100_000.0, shakeout_window_seconds=300)
    monitor = ShakeoutMonitor(settings)
    recorder = ShakeoutEventRecorder(tmp_path / "shakeout.jsonl")

    depth_payload = {
        "b": [["99", "1"], ["98", "1"]],
        "a": [["101", "12"], ["102", "10"]],
    }
    depth_analysis = monitor.apply_depth(depth_payload, now)
    recorder.record(
        kind="depth",
        payload=depth_payload,
        received_at=now,
        analysis=depth_analysis,
    )
    trade_payload = {"p": "100", "q": "2500", "m": True}
    trade_analysis = monitor.apply_trade(trade_payload, now)
    recorder.record(
        kind="trade",
        payload=trade_payload,
        received_at=now,
        analysis=trade_analysis,
    )

    replayed = replay_shakeout_events(tmp_path / "shakeout.jsonl", settings)
    summary = summarize(replayed)
    comparison = replay_shakeout_event_comparison(
        tmp_path / "shakeout.jsonl", settings
    )
    recorded_summary = summarize(comparison.recorded)

    assert len(replayed) == 2
    assert replayed[-1].direction == "DOWNSIDE SHAKEOUT RISK"
    assert summary.event_count == 2
    assert summary.max_score == replayed[-1].score
    assert len(comparison.recorded) == 2
    assert recorded_summary.event_count == 2
    assert recorded_summary.average_score > 0


def test_shakeout_recorder_serializes_stream_health_and_normalization(tmp_path) -> None:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    settings = Settings(whale_trade_usd=100_000.0)
    monitor = ShakeoutMonitor(settings)
    recorder = ShakeoutEventRecorder(tmp_path / "shakeout.jsonl")

    analysis = monitor.apply_trade({"p": "100", "q": "2500", "m": True}, now)
    recorder.record(
        kind="trade",
        payload={"p": "100", "q": "2500", "m": True},
        received_at=now,
        analysis=analysis,
    )

    raw = json.loads((tmp_path / "shakeout.jsonl").read_text(encoding="utf-8"))
    assert raw["analysis"]["stream_health"][1]["name"] == "aggTrade"
    assert raw["analysis"]["stream_health"][1]["event_count"] == 1
    assert "taker_flow_stress_ratio" in raw["analysis"]
