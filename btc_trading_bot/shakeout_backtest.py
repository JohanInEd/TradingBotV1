from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from btc_trading_bot.config import Settings
from btc_trading_bot.microstructure import replay_shakeout_events
from btc_trading_bot.models import ShakeoutAnalysis


@dataclass(frozen=True, slots=True)
class ShakeoutBacktestSummary:
    event_count: int
    status_counts: dict[str, int]
    max_score: float
    max_direction: str
    max_reason: str


def summarize(analyses: list[ShakeoutAnalysis]) -> ShakeoutBacktestSummary:
    if not analyses:
        return ShakeoutBacktestSummary(
            event_count=0,
            status_counts={},
            max_score=0.0,
            max_direction="N/A",
            max_reason="No shakeout events were replayed.",
        )
    peak = max(analyses, key=lambda analysis: analysis.score)
    return ShakeoutBacktestSummary(
        event_count=len(analyses),
        status_counts=dict(Counter(analysis.status for analysis in analyses)),
        max_score=peak.score,
        max_direction=peak.direction,
        max_reason=peak.reason,
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    if args.window_seconds is not None:
        settings = replace(settings, shakeout_window_seconds=args.window_seconds)
    if args.whale_trade_usd is not None:
        settings = replace(settings, whale_trade_usd=args.whale_trade_usd)

    summary = summarize(replay_shakeout_events(args.path, settings))
    print(f"Replayed events: {summary.event_count}")
    print(f"Status counts: {summary.status_counts}")
    print(f"Peak score: {summary.max_score:.2f}")
    print(f"Peak direction: {summary.max_direction}")
    print(f"Peak reason: {summary.max_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
