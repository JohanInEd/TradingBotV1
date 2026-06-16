from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from btc_trading_bot.config import Settings
from btc_trading_bot.microstructure import replay_shakeout_event_comparison
from btc_trading_bot.models import ShakeoutAnalysis


@dataclass(frozen=True, slots=True)
class ShakeoutBacktestSummary:
    event_count: int
    status_counts: dict[str, int]
    max_score: float
    max_direction: str
    max_reason: str
    average_score: float


def summarize(analyses: list[ShakeoutAnalysis]) -> ShakeoutBacktestSummary:
    if not analyses:
        return ShakeoutBacktestSummary(
            event_count=0,
            status_counts={},
            max_score=0.0,
            max_direction="N/A",
            max_reason="No shakeout events were replayed.",
            average_score=0.0,
        )
    peak = max(analyses, key=lambda analysis: analysis.score)
    return ShakeoutBacktestSummary(
        event_count=len(analyses),
        status_counts=dict(Counter(analysis.status for analysis in analyses)),
        max_score=peak.score,
        max_direction=peak.direction,
        max_reason=peak.reason,
        average_score=sum(analysis.score for analysis in analyses) / len(analyses),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay recorded Binance USD-M shakeout events"
    )
    parser.add_argument("path", type=Path, help="JSONL path from BOT_SHAKEOUT_EVENT_LOG")
    parser.add_argument(
        "--window-seconds",
        type=int,
        default=None,
        help="Override BOT_SHAKEOUT_WINDOW_SECONDS for replay",
    )
    parser.add_argument(
        "--whale-trade-usd",
        type=float,
        default=None,
        help="Override BOT_WHALE_TRADE_USD for replay",
    )
    parser.add_argument(
        "--baseline-window-seconds",
        type=int,
        default=None,
        help="Override BOT_SHAKEOUT_BASELINE_WINDOW_SECONDS for replay",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    if args.window_seconds is not None:
        settings = replace(settings, shakeout_window_seconds=args.window_seconds)
    if args.whale_trade_usd is not None:
        settings = replace(settings, whale_trade_usd=args.whale_trade_usd)
    if args.baseline_window_seconds is not None:
        settings = replace(
            settings,
            shakeout_baseline_window_seconds=args.baseline_window_seconds,
        )

    replay = replay_shakeout_event_comparison(args.path, settings)
    summary = summarize(replay.current)
    baseline = summarize(replay.recorded)
    print(f"Replayed events: {summary.event_count}")
    print(f"Current status counts: {summary.status_counts}")
    print(f"Current average score: {summary.average_score:.2f}")
    print(f"Current peak score: {summary.max_score:.2f}")
    print(f"Current peak direction: {summary.max_direction}")
    print(f"Current peak reason: {summary.max_reason}")
    if baseline.event_count:
        print(f"Recorded baseline events: {baseline.event_count}")
        print(f"Recorded baseline status counts: {baseline.status_counts}")
        print(f"Recorded baseline average score: {baseline.average_score:.2f}")
        print(f"Recorded baseline peak score: {baseline.max_score:.2f}")
        print(f"Peak score delta: {summary.max_score - baseline.max_score:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
