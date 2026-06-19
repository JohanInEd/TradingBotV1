from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.models import Evaluation, Headline, TechnicalAnalysis


DEFAULT_HORIZONS = (4, 12, 24)
SUMMARY_GROUPS = (
    "signal",
    "score_bucket",
    "sentiment",
    "macro_risk",
    "market_regime",
    "futures_context",
)


class SignalJournalRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._keys: set[tuple[str, str, str, str]] = set()
        self._load_existing_keys()

    def record(
        self,
        evaluation: Evaluation,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        settings: Settings,
    ) -> bool:
        record = build_journal_record(
            evaluation,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            settings=settings,
        )
        key = _record_key(record)
        if key in self._keys:
            return False
        with self.path.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    record,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
        self._keys.add(key)
        return True

    def _load_existing_keys(self) -> None:
        if not self.path.exists():
            return
        for row in load_journal(self.path):
            key = _record_key(row)
            if key is not None:
                self._keys.add(key)


def build_journal_record(
    evaluation: Evaluation,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    settings: Settings,
) -> dict[str, Any]:
    technical = evaluation.technical
    price = _finite_or_none(technical.close)
    record = {
        "schema_version": 1,
        "recorded_at": _iso(datetime.now(timezone.utc)),
        "exchange": exchange,
        "exchange_name": evaluation.market.exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "closed_candle_at": _iso(technical.candle_time),
        "evaluated_at": _iso(evaluation.evaluated_at),
        "price": price,
        "market_price": _finite_or_none(evaluation.market.price),
        "market": {
            "source": evaluation.market.source,
            "timestamp": _iso(evaluation.market.timestamp),
            "change_24h": _finite_or_none(evaluation.market.change_24h),
            "bid": _finite_or_none(evaluation.market.bid),
            "ask": _finite_or_none(evaluation.market.ask),
        },
        "candle": _candle_payload(technical),
        "technical": _technical_payload(technical),
        "signal": _jsonable(evaluation.signal),
        "futures": _jsonable(evaluation.futures),
        "sentiment": {
            "score": _finite_or_none(evaluation.sentiment.score),
            "label": evaluation.sentiment.label,
            "headline_count": len(evaluation.sentiment.headlines),
            "sources": [
                _sentiment_source_payload(item)
                for item in evaluation.sentiment.sources
            ],
            "headlines": [
                _headline_payload(item) for item in evaluation.sentiment.headlines
            ],
        },
        "macro": {
            "score": _finite_or_none(evaluation.macro.score),
            "status": evaluation.macro.status,
            "risk_multiplier": _finite_or_none(evaluation.macro.risk_multiplier),
            "alert_count": len(evaluation.macro.alerts),
            "alerts": [_headline_payload(item) for item in evaluation.macro.alerts],
        },
        "market_context": _jsonable(evaluation.market_context),
        "probability_forecast": _jsonable(evaluation.probability_forecast),
        "price_range": _jsonable(evaluation.price_range),
        "futures_metrics": _jsonable(evaluation.futures_metrics),
        "shakeout": _jsonable(evaluation.shakeout),
        "paper_risk": _paper_risk_payload(price, settings),
        "outcome": None,
    }
    return _jsonable(record)


@dataclass(frozen=True, slots=True)
class JournalOutcome:
    signal: str
    side: str | None
    score_bucket: str
    sentiment: str
    macro_risk: str
    market_regime: str
    futures_context: str
    movement_4h_percent: float | None
    movement_12h_percent: float | None
    movement_24h_percent: float | None
    direction_correct: bool | None
    long_result: str
    short_result: str
    long_r: float | None
    short_r: float | None
    signal_result: str
    signal_r: float | None


@dataclass(frozen=True, slots=True)
class JournalStats:
    sample_count: int
    directional_count: int
    direction_correct_count: int
    direction_accuracy: float | None
    win_count: int
    win_rate: float | None
    expected_r: float | None
    long_tp_count: int
    long_sl_count: int
    long_open_count: int
    short_tp_count: int
    short_sl_count: int
    short_open_count: int


@dataclass(frozen=True, slots=True)
class JournalReport:
    row_count: int
    pending_count: int
    overall: JournalStats
    groups: dict[str, dict[str, JournalStats]]


def load_journal(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def analyze_records(
    records: list[dict[str, Any]],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> JournalReport:
    outcomes = _build_outcomes(records, horizons=horizons)
    completed = [
        outcome for outcome in outcomes if outcome.movement_24h_percent is not None
    ]
    groups: dict[str, dict[str, JournalStats]] = {}
    for group_name in SUMMARY_GROUPS:
        grouped: dict[str, list[JournalOutcome]] = defaultdict(list)
        for outcome in completed:
            grouped[_group_value(outcome, group_name)].append(outcome)
        groups[group_name] = {
            label: _stats(items) for label, items in sorted(grouped.items())
        }
    return JournalReport(
        row_count=len(records),
        pending_count=len(outcomes) - len(completed),
        overall=_stats(completed),
        groups=groups,
    )


def analyze_journal(path: Path) -> JournalReport:
    return analyze_records(load_journal(path))


def format_report(report: JournalReport) -> str:
    lines = [
        f"Signal journal rows: {report.row_count}",
        (
            f"Completed 24h samples: {report.overall.sample_count}"
            f" ({report.pending_count} pending)"
        ),
        _stats_line("Overall", report.overall),
    ]
    for group_name in SUMMARY_GROUPS:
        group = report.groups.get(group_name, {})
        if not group:
            continue
        lines.append("")
        lines.append(f"By {group_name.replace('_', ' ')}:")
        for label, stats in group.items():
            lines.append(_stats_line(f"  {label}", stats))
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze BOT_SIGNAL_JOURNAL_PATH JSONL signal outcomes"
    )
    parser.add_argument("path", type=Path, help="JSONL path from BOT_SIGNAL_JOURNAL_PATH")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(format_report(analyze_journal(args.path)))
    return 0


def _build_outcomes(
    records: list[dict[str, Any]],
    *,
    horizons: tuple[int, ...],
) -> list[JournalOutcome]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        key = (
            str(row.get("exchange", "")),
            str(row.get("symbol", "")),
            str(row.get("timeframe", "")),
        )
        grouped[key].append(row)

    outcomes: list[JournalOutcome] = []
    for _, rows in grouped.items():
        rows.sort(key=lambda item: _parse_datetime(item.get("closed_candle_at")))
        for index, row in enumerate(rows):
            entry = _row_price(row)
            closed_at = _parse_datetime(row.get("closed_candle_at"))
            timeframe_hours = _timeframe_hours(str(row.get("timeframe", "4h")))
            movements = {
                hours: _movement_after(
                    rows,
                    index,
                    entry,
                    closed_at,
                    timeframe_hours,
                    hours,
                )
                for hours in horizons
            }
            path_rows = _future_path(rows, index, closed_at, timeframe_hours, 24)
            long_result, long_r = _trade_outcome(row, path_rows, side="LONG")
            short_result, short_r = _trade_outcome(row, path_rows, side="SHORT")
            side = _signal_side(row)
            signal_result = "N/A"
            signal_r = None
            direction_correct = None
            movement_24h = movements.get(24)
            if side == "LONG":
                signal_result = long_result
                signal_r = long_r
                if movement_24h is not None:
                    direction_correct = movement_24h > 0
            elif side == "SHORT":
                signal_result = short_result
                signal_r = short_r
                if movement_24h is not None:
                    direction_correct = movement_24h < 0

            outcomes.append(
                JournalOutcome(
                    signal=_nested_str(row, "signal", "signal", default="UNKNOWN"),
                    side=side,
                    score_bucket=_score_bucket(
                        _nested_float(row, "signal", "score")
                    ),
                    sentiment=_nested_str(
                        row, "sentiment", "label", default="UNKNOWN"
                    ),
                    macro_risk=_nested_str(row, "macro", "status", default="UNKNOWN"),
                    market_regime=_market_regime(row),
                    futures_context=_futures_context(row),
                    movement_4h_percent=movements.get(4),
                    movement_12h_percent=movements.get(12),
                    movement_24h_percent=movement_24h,
                    direction_correct=direction_correct,
                    long_result=long_result,
                    short_result=short_result,
                    long_r=long_r,
                    short_r=short_r,
                    signal_result=signal_result,
                    signal_r=signal_r,
                )
            )
    return outcomes


def _stats(outcomes: list[JournalOutcome]) -> JournalStats:
    directional = [item for item in outcomes if item.side in {"LONG", "SHORT"}]
    direction_known = [
        item for item in directional if item.direction_correct is not None
    ]
    direction_correct_count = sum(
        1 for item in direction_known if item.direction_correct
    )
    signal_r_values = [
        item.signal_r for item in directional if item.signal_r is not None
    ]
    win_count = sum(1 for value in signal_r_values if value > 0)
    return JournalStats(
        sample_count=len(outcomes),
        directional_count=len(directional),
        direction_correct_count=direction_correct_count,
        direction_accuracy=(
            direction_correct_count / len(direction_known)
            if direction_known
            else None
        ),
        win_count=win_count,
        win_rate=win_count / len(signal_r_values) if signal_r_values else None,
        expected_r=(
            sum(signal_r_values) / len(signal_r_values)
            if signal_r_values
            else None
        ),
        long_tp_count=sum(1 for item in outcomes if item.long_result == "TP"),
        long_sl_count=sum(1 for item in outcomes if item.long_result == "SL"),
        long_open_count=sum(1 for item in outcomes if item.long_result == "OPEN"),
        short_tp_count=sum(1 for item in outcomes if item.short_result == "TP"),
        short_sl_count=sum(1 for item in outcomes if item.short_result == "SL"),
        short_open_count=sum(1 for item in outcomes if item.short_result == "OPEN"),
    )


def _movement_after(
    rows: list[dict[str, Any]],
    index: int,
    entry: float | None,
    closed_at: datetime,
    timeframe_hours: float,
    horizon_hours: int,
) -> float | None:
    if entry is None or entry <= 0 or timeframe_hours <= 0:
        return None
    offset = horizon_hours / timeframe_hours
    if not offset.is_integer():
        return None
    target_index = index + int(offset)
    if target_index >= len(rows):
        return None
    target_time = closed_at + timedelta(hours=horizon_hours)
    row = rows[target_index]
    actual_time = _parse_datetime(row.get("closed_candle_at"))
    if abs((actual_time - target_time).total_seconds()) > 60:
        return None
    target_price = _row_price(row)
    if target_price is None:
        return None
    return (target_price / entry - 1.0) * 100.0


def _future_path(
    rows: list[dict[str, Any]],
    index: int,
    closed_at: datetime,
    timeframe_hours: float,
    horizon_hours: int,
) -> list[dict[str, Any]]:
    if timeframe_hours <= 0:
        return []
    offset = horizon_hours / timeframe_hours
    if not offset.is_integer():
        return []
    end_index = index + int(offset)
    if end_index >= len(rows):
        return []
    target_time = closed_at + timedelta(hours=horizon_hours)
    actual_time = _parse_datetime(rows[end_index].get("closed_candle_at"))
    if abs((actual_time - target_time).total_seconds()) > 60:
        return []
    return rows[index + 1 : end_index + 1]


def _trade_outcome(
    setup: dict[str, Any],
    path_rows: list[dict[str, Any]],
    *,
    side: str,
) -> tuple[str, float | None]:
    if not path_rows:
        return "PENDING", None
    levels = _nested_dict(setup, "paper_risk", side.lower())
    entry = _to_float(levels.get("entry_price")) if levels else None
    stop = _to_float(levels.get("stop_loss")) if levels else None
    target = _to_float(levels.get("take_profit")) if levels else None
    if entry is None or stop is None or target is None:
        return "UNKNOWN", None

    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return "UNKNOWN", None

    for row in path_rows:
        candle = _nested_dict(row, "candle")
        high = _to_float(candle.get("high"))
        low = _to_float(candle.get("low"))
        if high is None or low is None:
            return "UNKNOWN", None
        if side == "LONG":
            if low <= stop:
                return "SL", -1.0
            if high >= target:
                return "TP", _reward_to_risk(entry, stop, target)
        else:
            if high >= stop:
                return "SL", -1.0
            if low <= target:
                return "TP", _reward_to_risk(entry, stop, target)

    horizon_close = _row_price(path_rows[-1])
    if horizon_close is None:
        return "OPEN", None
    if side == "LONG":
        r_multiple = (horizon_close - entry) / stop_distance
    else:
        r_multiple = (entry - horizon_close) / stop_distance
    return "OPEN", _clamp_r(
        r_multiple,
        _reward_to_risk(entry, stop, target),
    )


def _reward_to_risk(entry: float, stop: float, target: float) -> float:
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0
    return abs(target - entry) / stop_distance


def _clamp_r(value: float, reward_to_risk: float) -> float:
    return max(-1.0, min(reward_to_risk, value))


def _signal_side(row: dict[str, Any]) -> str | None:
    futures_side = _nested_str(row, "futures", "side", default="")
    if futures_side in {"LONG", "SHORT"}:
        return futures_side
    signal = _nested_str(row, "signal", "signal", default="")
    if signal == "STRONG BUY":
        return "LONG"
    if signal == "STRONG SELL":
        return "SHORT"
    return None


def _paper_risk_payload(
    entry: float | None,
    settings: Settings,
) -> dict[str, Any]:
    payload = {
        "stop_loss_percent": settings.stop_loss_percent,
        "reward_to_risk": settings.reward_to_risk,
        "long": None,
        "short": None,
    }
    if entry is None or entry <= 0:
        return payload
    long_stop = entry * (1.0 - settings.stop_loss_percent)
    long_target = entry + ((entry - long_stop) * settings.reward_to_risk)
    short_stop = entry * (1.0 + settings.stop_loss_percent)
    short_target = entry - ((short_stop - entry) * settings.reward_to_risk)
    payload["long"] = {
        "entry_price": entry,
        "stop_loss": long_stop,
        "take_profit": long_target,
    }
    payload["short"] = {
        "entry_price": entry,
        "stop_loss": short_stop,
        "take_profit": short_target,
    }
    return payload


def _technical_payload(technical: TechnicalAnalysis) -> dict[str, Any]:
    return {
        "score": _finite_or_none(technical.score),
        "base_score": _finite_or_none(technical.base_score),
        "ema20": _finite_or_none(technical.ema20),
        "ema50": _finite_or_none(technical.ema50),
        "ema_status": technical.ema_status,
        "rsi14": _finite_or_none(technical.rsi14),
        "rsi_status": technical.rsi_status,
        "macd": _finite_or_none(technical.macd),
        "macd_signal": _finite_or_none(technical.macd_signal),
        "macd_histogram": _finite_or_none(technical.macd_histogram),
        "macd_status": technical.macd_status,
        "daily_trend": _jsonable(technical.daily_trend),
        "hourly_entry": _jsonable(technical.hourly_entry),
    }


def _candle_payload(technical: TechnicalAnalysis) -> dict[str, Any]:
    return {
        "time": _iso(technical.candle_time),
        "open": _finite_or_none(technical.open),
        "high": _finite_or_none(technical.high),
        "low": _finite_or_none(technical.low),
        "close": _finite_or_none(technical.close),
    }


def _headline_payload(headline: Headline) -> dict[str, Any]:
    return {
        "title": headline.title,
        "source": headline.source,
        "url": headline.url,
        "published_at": _iso(headline.published_at),
        "category": headline.category,
        "sentiment": _finite_or_none(headline.sentiment),
    }


def _sentiment_source_payload(source: Any) -> dict[str, Any]:
    return {
        "name": getattr(source, "name", ""),
        "score": _finite_or_none(getattr(source, "score", None)),
        "label": getattr(source, "label", ""),
        "detail": getattr(source, "detail", ""),
        "updated_at": _iso(getattr(source, "updated_at", None)),
    }


def _record_key(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    closed_at = row.get("closed_candle_at")
    if closed_at is None:
        return None
    return (
        str(row.get("exchange", "")),
        str(row.get("symbol", "")),
        str(row.get("timeframe", "")),
        str(closed_at),
    )


def _stats_line(label: str, stats: JournalStats) -> str:
    return (
        f"{label}: n={stats.sample_count}"
        f" directional={stats.directional_count}"
        f" dir={_pct(stats.direction_accuracy)}"
        f" win={_pct(stats.win_rate)}"
        f" expR={_signed(stats.expected_r)}"
        f" long TP/SL/open={stats.long_tp_count}/{stats.long_sl_count}/{stats.long_open_count}"
        f" short TP/SL/open={stats.short_tp_count}/{stats.short_sl_count}/{stats.short_open_count}"
    )


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _signed(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}"


def _group_value(outcome: JournalOutcome, group_name: str) -> str:
    return str(getattr(outcome, group_name))


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.65:
        return ">= +0.65"
    if score >= 0.25:
        return "+0.25 to +0.65"
    if score > -0.25:
        return "-0.25 to +0.25"
    if score > -0.65:
        return "-0.65 to -0.25"
    return "<= -0.65"


def _market_regime(row: dict[str, Any]) -> str:
    context = _nested_dict(row, "market_context")
    if not context:
        return "UNKNOWN"
    volatility = str(context.get("volatility_regime") or "UNKNOWN")
    structure = str(context.get("structure_regime") or "UNKNOWN")
    return f"{volatility} / {structure}"


def _futures_context(row: dict[str, Any]) -> str:
    futures_side = _nested_str(row, "futures", "side", default="FLAT")
    shakeout = _nested_dict(row, "shakeout")
    if not shakeout:
        return futures_side
    status = str(shakeout.get("status") or "UNKNOWN")
    direction = str(shakeout.get("direction") or "UNKNOWN")
    return f"{futures_side} / {status} / {direction}"


def _row_price(row: dict[str, Any]) -> float | None:
    price = _to_float(row.get("price"))
    if price is not None:
        return price
    candle = _nested_dict(row, "candle")
    return _to_float(candle.get("close"))


def _nested_dict(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key)
    return value if isinstance(value, dict) else {}


def _nested_float(row: dict[str, Any], *keys: str) -> float | None:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return _to_float(value)


def _nested_str(row: dict[str, Any], *keys: str, default: str) -> str:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else str(value)


def _timeframe_hours(value: str) -> float:
    text = value.strip().lower()
    if text.endswith("m"):
        return float(text[:-1]) / 60.0
    if text.endswith("h"):
        return float(text[:-1])
    if text.endswith("d"):
        return float(text[:-1]) * 24.0
    return 4.0


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _finite_or_none(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    return number if math.isfinite(number) else None


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


if __name__ == "__main__":
    raise SystemExit(main())
