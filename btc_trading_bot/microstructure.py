from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    FuturesMetrics,
    MicrostructureStreamHealth,
    ShakeoutAnalysis,
)


@dataclass(frozen=True, slots=True)
class _FlowEvent:
    timestamp: datetime
    side: str
    notional: float
    is_large: bool = False


@dataclass(frozen=True, slots=True)
class _OpenInterestSample:
    timestamp: datetime
    amount: float


@dataclass(frozen=True, slots=True)
class _DepthSample:
    timestamp: datetime
    bid_depth: float
    ask_depth: float


@dataclass(slots=True)
class _StreamStats:
    name: str
    event_count: int = 0
    last_event_at: datetime | None = None


class ShakeoutMonitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._depth_bids: list[tuple[float, float]] = []
        self._depth_asks: list[tuple[float, float]] = []
        self._trades: deque[_FlowEvent] = deque()
        self._liquidations: deque[_FlowEvent] = deque()
        self._depth_samples: deque[_DepthSample] = deque()
        self._open_interest: deque[_OpenInterestSample] = deque(maxlen=20)
        self._top_trader_long_short_ratio: float | None = None
        self._updated_at: datetime | None = None
        self._stream_stats = {
            "depth": _StreamStats("depth"),
            "aggTrade": _StreamStats("aggTrade"),
            "forceOrder": _StreamStats("forceOrder"),
        }

    def apply_depth(self, payload: dict[str, Any], received_at: datetime) -> ShakeoutAnalysis:
        self._depth_bids = _levels(payload.get("b"))
        self._depth_asks = _levels(payload.get("a"))
        bid_depth = _depth_usd(self._depth_bids)
        ask_depth = _depth_usd(self._depth_asks)
        if bid_depth is not None and ask_depth is not None:
            self._depth_samples.append(
                _DepthSample(received_at, bid_depth, ask_depth)
            )
        self._mark_stream("depth", received_at)
        self._updated_at = received_at
        return self.analyze(received_at)

    def apply_trade(self, payload: dict[str, Any], received_at: datetime) -> ShakeoutAnalysis:
        price = _number(payload.get("p"))
        quantity = _number(payload.get("q"))
        if price is not None and quantity is not None:
            notional = price * quantity
            side = "SELL" if payload.get("m") is True else "BUY"
            self._trades.append(
                _FlowEvent(
                    timestamp=received_at,
                    side=side,
                    notional=notional,
                    is_large=notional >= self._large_trade_threshold(received_at),
                )
            )
        self._mark_stream("aggTrade", received_at)
        self._updated_at = received_at
        return self.analyze(received_at)

    def apply_liquidation(
        self, payload: dict[str, Any], received_at: datetime
    ) -> ShakeoutAnalysis:
        order = payload.get("o") if isinstance(payload.get("o"), dict) else payload
        side = str(order.get("S", "")).upper()
        price = _number(order.get("ap")) or _number(order.get("p"))
        quantity = _number(order.get("z")) or _number(order.get("q"))
        if side in {"BUY", "SELL"} and price is not None and quantity is not None:
            self._liquidations.append(
                _FlowEvent(
                    timestamp=received_at,
                    side=side,
                    notional=price * quantity,
                    is_large=True,
                )
            )
        self._mark_stream("forceOrder", received_at)
        self._updated_at = received_at
        return self.analyze(received_at)

    def apply_futures_metrics(
        self, metrics: FuturesMetrics | None, received_at: datetime
    ) -> ShakeoutAnalysis:
        if metrics is not None:
            if metrics.open_interest_amount is not None:
                self._open_interest.append(
                    _OpenInterestSample(received_at, metrics.open_interest_amount)
                )
            self._top_trader_long_short_ratio = metrics.long_short_ratio
            self._updated_at = received_at
        return self.analyze(received_at)

    def analyze(self, now: datetime | None = None) -> ShakeoutAnalysis:
        now = now or datetime.now(timezone.utc)
        self._prune(now)
        bid_depth = _depth_usd(self._depth_bids)
        ask_depth = _depth_usd(self._depth_asks)
        book_imbalance = _imbalance(bid_depth, ask_depth)

        taker_buy = _decayed_sum(
            self._trades,
            now,
            half_life_seconds=self.settings.shakeout_window_seconds,
            side="BUY",
        )
        taker_sell = _decayed_sum(
            self._trades,
            now,
            half_life_seconds=self.settings.shakeout_window_seconds,
            side="SELL",
        )
        taker_imbalance = _imbalance(taker_buy, taker_sell)
        large_threshold = self._large_trade_threshold(now)
        large_trades = [
            event for event in self._trades if event.notional >= large_threshold
        ]
        large_net = sum(
            _freshness_weight(event.timestamp, now, self.settings.shakeout_window_seconds)
            * (event.notional if event.side == "BUY" else -event.notional)
            for event in large_trades
        )

        liq_buy = _decayed_sum(
            self._liquidations,
            now,
            half_life_seconds=self.settings.shakeout_window_seconds,
            side="BUY",
        )
        liq_sell = _decayed_sum(
            self._liquidations,
            now,
            half_life_seconds=self.settings.shakeout_window_seconds,
            side="SELL",
        )
        liq_imbalance = _imbalance(liq_buy, liq_sell)
        oi_change = self._open_interest_change_percent()
        bid_depth_baseline, ask_depth_baseline = self._depth_baselines(now)
        taker_flow_baseline = self._flow_baseline(self._trades, now)
        large_trade_baseline = self._large_trade_baseline(now, large_threshold)
        liquidation_baseline = self._flow_baseline(self._liquidations, now)

        upside, downside, reasons, stress = self._score(
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            bid_depth_baseline=bid_depth_baseline,
            ask_depth_baseline=ask_depth_baseline,
            book_imbalance=book_imbalance,
            taker_imbalance=taker_imbalance,
            taker_total=taker_buy + taker_sell,
            taker_flow_baseline=taker_flow_baseline,
            large_net=large_net,
            large_trade_trigger=large_threshold,
            large_trade_baseline=large_trade_baseline,
            liq_imbalance=liq_imbalance,
            liq_total=liq_buy + liq_sell,
            liquidation_baseline=liquidation_baseline,
            oi_change=oi_change,
        )
        score = min(1.0, max(upside, downside))
        status = _status(score)
        if score < 0.15:
            direction = "BALANCED"
        elif abs(upside - downside) < 0.12:
            direction = "TWO-SIDED VOLATILITY RISK"
        elif upside > downside:
            direction = "UPSIDE SQUEEZE RISK"
        else:
            direction = "DOWNSIDE SHAKEOUT RISK"

        return ShakeoutAnalysis(
            status=status,
            direction=direction,
            score=score,
            order_book_imbalance=book_imbalance,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            taker_buy_usd=taker_buy,
            taker_sell_usd=taker_sell,
            large_trade_count=len(large_trades),
            large_trade_net_usd=large_net,
            liquidation_buy_usd=liq_buy,
            liquidation_sell_usd=liq_sell,
            liquidation_count=len(self._liquidations),
            open_interest_change_percent=oi_change,
            top_trader_long_short_ratio=self._top_trader_long_short_ratio,
            reason="; ".join(reasons) if reasons else "No dominant public microstructure stress detected.",
            updated_at=self._updated_at,
            depth_stress_ratio=stress["depth"],
            taker_flow_stress_ratio=stress["taker_flow"],
            large_trade_stress_ratio=stress["large_trade"],
            liquidation_stress_ratio=stress["liquidation"],
            stream_health=self._stream_health(now),
        )

    def _score(
        self,
        *,
        bid_depth: float | None,
        ask_depth: float | None,
        bid_depth_baseline: float | None,
        ask_depth_baseline: float | None,
        book_imbalance: float | None,
        taker_imbalance: float | None,
        taker_total: float,
        taker_flow_baseline: float | None,
        large_net: float,
        large_trade_trigger: float,
        large_trade_baseline: float | None,
        liq_imbalance: float | None,
        liq_total: float,
        liquidation_baseline: float | None,
        oi_change: float | None,
    ) -> tuple[float, float, list[str], dict[str, float | None]]:
        upside = 0.0
        downside = 0.0
        reasons: list[str] = []
        window_label = f"decayed {_window_label(self.settings.shakeout_window_seconds)}"
        stress: dict[str, float | None] = {
            "depth": None,
            "taker_flow": None,
            "large_trade": None,
            "liquidation": None,
        }

        if bid_depth is not None and ask_depth is not None and bid_depth > 0 and ask_depth > 0:
            ask_ratio = ask_depth / bid_depth
            bid_ratio = bid_depth / ask_depth
            ask_stress = _depletion_ratio(ask_depth, ask_depth_baseline)
            bid_stress = _depletion_ratio(bid_depth, bid_depth_baseline)
            stress["depth"] = max(
                value
                for value in (
                    _thin_depth_ratio(ask_depth, ask_depth_baseline),
                    _thin_depth_ratio(bid_depth, bid_depth_baseline),
                    0.0,
                )
                if value is not None
            )
            if ask_ratio < 0.45 or (ask_stress is not None and ask_stress >= 0.55):
                contribution = 0.30 if ask_stress is None else min(0.34, 0.16 + ask_stress * 0.26)
                upside += contribution
                reasons.append(
                    _depth_reason(
                        "ask",
                        ask_depth,
                        bid_depth,
                        ask_depth_baseline,
                        ask_stress,
                    )
                )
            elif ask_ratio < 0.70 or (ask_stress is not None and ask_stress >= 0.35):
                contribution = 0.20 if ask_stress is None else min(0.24, 0.10 + ask_stress * 0.22)
                upside += contribution
                reasons.append(
                    _depth_reason(
                        "ask",
                        ask_depth,
                        bid_depth,
                        ask_depth_baseline,
                        ask_stress,
                    )
                )
            if bid_ratio < 0.45 or (bid_stress is not None and bid_stress >= 0.55):
                contribution = 0.30 if bid_stress is None else min(0.34, 0.16 + bid_stress * 0.26)
                downside += contribution
                reasons.append(
                    _depth_reason(
                        "bid",
                        bid_depth,
                        ask_depth,
                        bid_depth_baseline,
                        bid_stress,
                    )
                )
            elif bid_ratio < 0.70 or (bid_stress is not None and bid_stress >= 0.35):
                contribution = 0.20 if bid_stress is None else min(0.24, 0.10 + bid_stress * 0.22)
                downside += contribution
                reasons.append(
                    _depth_reason(
                        "bid",
                        bid_depth,
                        ask_depth,
                        bid_depth_baseline,
                        bid_stress,
                    )
                )
        if book_imbalance is not None and abs(book_imbalance) > 0.40:
            if book_imbalance > 0:
                upside += 0.06
            else:
                downside += 0.06

        flow_ratio = _stress_ratio(taker_total, taker_flow_baseline)
        stress["taker_flow"] = flow_ratio
        min_flow = self.settings.whale_trade_usd * 0.20
        if taker_flow_baseline is not None:
            min_flow = min(min_flow, taker_flow_baseline * 1.50)
        if (
            taker_imbalance is not None
            and (taker_total >= min_flow or (flow_ratio is not None and flow_ratio >= 1.50))
            and abs(taker_imbalance) >= 0.25
        ):
            normalized_bonus = min(0.08, max(0.0, (flow_ratio or 1.0) - 1.0) * 0.04)
            contribution = min(0.30, 0.10 + abs(taker_imbalance) * 0.16 + normalized_bonus)
            net_flow = taker_total * abs(taker_imbalance)
            if taker_imbalance > 0:
                upside += contribution
                reasons.append(
                    _flow_reason(
                        "aggressive buy flow",
                        net_flow,
                        window_label,
                        flow_ratio,
                    )
                )
            else:
                downside += contribution
                reasons.append(
                    _flow_reason(
                        "aggressive sell flow",
                        net_flow,
                        window_label,
                        flow_ratio,
                    )
                )

        large_ratio = _stress_ratio(abs(large_net), large_trade_baseline)
        stress["large_trade"] = large_ratio
        if abs(large_net) >= large_trade_trigger or (large_ratio is not None and large_ratio >= 1.25):
            ratio_bonus = min(0.08, max(0.0, (large_ratio or 1.0) - 1.0) * 0.04)
            contribution = min(0.20, 0.08 + ratio_bonus + abs(large_net) / max(large_trade_trigger * 6, 1.0) * 0.12)
            if large_net > 0:
                upside += contribution
                reasons.append(
                    _flow_reason(
                        "large taker buys",
                        abs(large_net),
                        "net",
                        large_ratio,
                    )
                )
            else:
                downside += contribution
                reasons.append(
                    _flow_reason(
                        "large taker sells",
                        abs(large_net),
                        "net",
                        large_ratio,
                    )
                )

        liquidation_ratio = _stress_ratio(liq_total, liquidation_baseline)
        stress["liquidation"] = liquidation_ratio
        min_liquidations = max(5_000.0, self.settings.whale_trade_usd * 0.05)
        if liquidation_baseline is not None:
            min_liquidations = min(min_liquidations, liquidation_baseline * 1.50)
        if (
            liq_imbalance is not None
            and (
                liq_total >= min_liquidations
                or (liquidation_ratio is not None and liquidation_ratio >= 1.50)
            )
            and abs(liq_imbalance) >= 0.25
        ):
            normalized_bonus = min(
                0.10,
                max(0.0, (liquidation_ratio or 1.0) - 1.0) * 0.05,
            )
            contribution = min(0.32, 0.10 + abs(liq_imbalance) * 0.18 + normalized_bonus)
            net_liquidations = liq_total * abs(liq_imbalance)
            if liq_imbalance > 0:
                upside += contribution
                reasons.append(
                    _flow_reason(
                        "short liquidation burst",
                        net_liquidations,
                        window_label,
                        liquidation_ratio,
                    )
                )
            else:
                downside += contribution
                reasons.append(
                    _flow_reason(
                        "long liquidation burst",
                        net_liquidations,
                        window_label,
                        liquidation_ratio,
                    )
                )

        ratio = self._top_trader_long_short_ratio
        if ratio is not None:
            if ratio >= 2.00:
                downside += 0.16
                reasons.append(f"top traders crowded long (L/S {ratio:.2f})")
            elif ratio >= 1.50:
                downside += 0.10
                reasons.append(f"top traders crowded long (L/S {ratio:.2f})")
            elif ratio <= 0.50:
                upside += 0.16
                reasons.append(f"top traders crowded short (L/S {ratio:.2f})")
            elif ratio <= 0.75:
                upside += 0.10
                reasons.append(f"top traders crowded short (L/S {ratio:.2f})")

        if oi_change is not None and abs(oi_change) >= 1.0:
            if oi_change > 0:
                contribution = 0.07 if oi_change >= 3.0 else 0.04
                upside += contribution
                downside += contribution
                reasons.append(f"open interest building ({oi_change:+.2f}%)")
            elif taker_imbalance is not None:
                if taker_imbalance > 0:
                    upside += 0.06
                elif taker_imbalance < 0:
                    downside += 0.06
                reasons.append(f"open interest flushing ({oi_change:+.2f}%)")

        return min(1.0, upside), min(1.0, downside), reasons[:5], stress

    def _open_interest_change_percent(self) -> float | None:
        if len(self._open_interest) < 2:
            return None
        first = self._open_interest[0].amount
        latest = self._open_interest[-1].amount
        if first <= 0:
            return None
        return (latest - first) / first * 100.0

    def _depth_baselines(self, now: datetime) -> tuple[float | None, float | None]:
        samples = [
            sample
            for sample in self._depth_samples
            if sample.timestamp <= now
            and (now - sample.timestamp).total_seconds()
            <= self.settings.shakeout_baseline_window_seconds
        ]
        if len(samples) < 3:
            return None, None
        return (
            median(sample.bid_depth for sample in samples),
            median(sample.ask_depth for sample in samples),
        )

    def _flow_baseline(
        self, events: deque[_FlowEvent], now: datetime
    ) -> float | None:
        if len(events) < 3:
            return None
        window = self.settings.shakeout_window_seconds
        horizon = self.settings.shakeout_baseline_window_seconds
        cutoff = now - timedelta(seconds=_baseline_exclusion_seconds(window))
        eligible = [
            event
            for event in events
            if event.timestamp < cutoff
            and (now - event.timestamp).total_seconds() <= horizon
        ]
        if len(eligible) < 3:
            return None
        oldest = min(event.timestamp for event in eligible)
        newest = max(event.timestamp for event in eligible)
        span = max(window, (newest - oldest).total_seconds())
        total = sum(event.notional for event in eligible)
        return max(1.0, total / span * window)

    def _large_trade_threshold(self, now: datetime) -> float:
        horizon = self.settings.shakeout_baseline_window_seconds
        cutoff = now - timedelta(
            seconds=_baseline_exclusion_seconds(self.settings.shakeout_window_seconds)
        )
        prior = [
            event.notional
            for event in self._trades
            if event.timestamp < cutoff
            and (now - event.timestamp).total_seconds() <= horizon
        ]
        if len(prior) < 5:
            return self.settings.whale_trade_usd
        dynamic = median(prior) * 4.0
        floor = self.settings.whale_trade_usd * 0.25
        return max(floor, dynamic)

    def _large_trade_baseline(
        self, now: datetime, threshold: float
    ) -> float | None:
        horizon = self.settings.shakeout_baseline_window_seconds
        cutoff = now - timedelta(
            seconds=_baseline_exclusion_seconds(self.settings.shakeout_window_seconds)
        )
        eligible = [
            event
            for event in self._trades
            if event.timestamp < cutoff
            and event.notional >= threshold
            and (now - event.timestamp).total_seconds() <= horizon
        ]
        if len(eligible) < 2:
            return None
        oldest = min(event.timestamp for event in eligible)
        newest = max(event.timestamp for event in eligible)
        span = max(self.settings.shakeout_window_seconds, (newest - oldest).total_seconds())
        total = sum(event.notional for event in eligible)
        return max(threshold, total / span * self.settings.shakeout_window_seconds)

    def _mark_stream(self, name: str, received_at: datetime) -> None:
        stats = self._stream_stats[name]
        stats.event_count += 1
        stats.last_event_at = received_at

    def _stream_health(self, now: datetime) -> tuple[MicrostructureStreamHealth, ...]:
        health: list[MicrostructureStreamHealth] = []
        stale_seconds = self.settings.stream_stale_seconds
        for name in ("depth", "aggTrade", "forceOrder"):
            stats = self._stream_stats[name]
            age = (
                (now - stats.last_event_at).total_seconds()
                if stats.last_event_at is not None
                else None
            )
            if age is None:
                status = "WAITING"
            elif age <= stale_seconds:
                status = "LIVE"
            elif age <= stale_seconds * 3:
                status = "STALE"
            else:
                status = "QUIET"
            health.append(
                MicrostructureStreamHealth(
                    name=stats.name,
                    status=status,
                    event_count=stats.event_count,
                    last_event_at=stats.last_event_at,
                    last_event_age_seconds=age,
                )
            )
        return tuple(health)

    def _prune(self, now: datetime) -> None:
        horizon = max(
            self.settings.shakeout_baseline_window_seconds,
            self.settings.shakeout_window_seconds * 3,
        )
        cutoff = now - timedelta(seconds=horizon)
        for events in (self._trades, self._liquidations):
            while events and events[0].timestamp < cutoff:
                events.popleft()
        while self._depth_samples and self._depth_samples[0].timestamp < cutoff:
            self._depth_samples.popleft()
        while self._open_interest and self._open_interest[0].timestamp < cutoff:
            self._open_interest.popleft()


def _levels(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, list):
        return []
    levels: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        price = _number(item[0])
        quantity = _number(item[1])
        if price is not None and quantity is not None and price > 0 and quantity > 0:
            levels.append((price, quantity))
    return levels


def _depth_usd(levels: list[tuple[float, float]]) -> float | None:
    if not levels:
        return None
    return sum(price * quantity for price, quantity in levels)


def _imbalance(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    total = left + right
    if total <= 0:
        return None
    return (left - right) / total


def _decayed_sum(
    events: deque[_FlowEvent],
    now: datetime,
    *,
    half_life_seconds: int,
    side: str | None = None,
) -> float:
    return sum(
        event.notional
        * _freshness_weight(event.timestamp, now, half_life_seconds)
        for event in events
        if side is None or event.side == side
    )


def _freshness_weight(
    timestamp: datetime, now: datetime, half_life_seconds: int
) -> float:
    age = max(0.0, (now - timestamp).total_seconds())
    half_life = max(30.0, half_life_seconds / 2.0)
    return math.exp(-age / half_life)


def _depletion_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - value / baseline))


def _stress_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


def _thin_depth_ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0 or value <= 0:
        return None
    return max(0.0, baseline / value) if value < baseline else 0.0


def _baseline_exclusion_seconds(window_seconds: int) -> int:
    return min(60, max(5, int(window_seconds * 0.10)))


def _depth_reason(
    side: str,
    depth: float,
    opposite_depth: float,
    baseline: float | None,
    stress: float | None,
) -> str:
    reason = (
        f"thin {side} liquidity ({_compact_usd(depth)} {side} vs "
        f"{_compact_usd(opposite_depth)} opposite)"
    )
    if baseline is not None and stress is not None:
        reason += f", {stress * 100:.0f}% below baseline {_compact_usd(baseline)}"
    return reason


def _flow_reason(
    label: str,
    value: float,
    suffix: str,
    ratio: float | None,
) -> str:
    reason = f"{label} ({_compact_usd(value)} {suffix})"
    if ratio is not None:
        reason += f", {ratio:.1f}x baseline"
    return reason


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _status(score: float) -> str:
    if score >= 0.70:
        return "HIGH"
    if score >= 0.45:
        return "MEDIUM"
    if score >= 0.20:
        return "LOW"
    return "CALM"


class ShakeoutEventRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        kind: str,
        received_at: datetime,
        payload: Any,
        analysis: ShakeoutAnalysis,
    ) -> None:
        event = {
            "kind": kind,
            "received_at": received_at.isoformat(),
            "payload": _jsonable(payload),
            "analysis": _jsonable(analysis),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, separators=(",", ":")) + "\n")


def replay_shakeout_events(
    path: Path,
    settings: Settings,
) -> list[ShakeoutAnalysis]:
    return replay_shakeout_event_comparison(path, settings).current


@dataclass(frozen=True, slots=True)
class ShakeoutReplay:
    current: list[ShakeoutAnalysis]
    recorded: list[ShakeoutAnalysis]


def replay_shakeout_event_comparison(
    path: Path,
    settings: Settings,
) -> ShakeoutReplay:
    monitor = ShakeoutMonitor(settings)
    current: list[ShakeoutAnalysis] = []
    recorded: list[ShakeoutAnalysis] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            event = json.loads(line)
            kind = str(event.get("kind", ""))
            received_at = _parse_datetime(event.get("received_at"))
            payload = event.get("payload")
            baseline = _shakeout_analysis_from_payload(event.get("analysis"))
            if baseline is not None:
                recorded.append(baseline)
            if kind == "depth":
                current.append(monitor.apply_depth(payload, received_at))
            elif kind == "trade":
                current.append(monitor.apply_trade(payload, received_at))
            elif kind == "liquidation":
                current.append(monitor.apply_liquidation(payload, received_at))
            elif kind == "futures_metrics":
                current.append(
                    monitor.apply_futures_metrics(
                        _futures_metrics_from_payload(payload), received_at
                    )
                )
    return ShakeoutReplay(current=current, recorded=recorded)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed
        return parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _futures_metrics_from_payload(payload: Any) -> FuturesMetrics | None:
    if not isinstance(payload, dict):
        return None
    updated_at = _parse_datetime(payload.get("updated_at"))
    next_funding_at = (
        _parse_datetime(payload["next_funding_at"])
        if payload.get("next_funding_at")
        else None
    )
    return FuturesMetrics(
        mark_price=_number(payload.get("mark_price")),
        index_price=_number(payload.get("index_price")),
        funding_rate=_number(payload.get("funding_rate")),
        next_funding_at=next_funding_at,
        open_interest_amount=_number(payload.get("open_interest_amount")),
        open_interest_value=_number(payload.get("open_interest_value")),
        long_short_ratio=_number(payload.get("long_short_ratio")),
        updated_at=updated_at,
        top_trader_long_short_ratio=_number(
            payload.get("top_trader_long_short_ratio")
        ),
        top_trader_position_ratio=_number(payload.get("top_trader_position_ratio")),
        taker_buy_sell_ratio=_number(payload.get("taker_buy_sell_ratio")),
        taker_buy_volume=_number(payload.get("taker_buy_volume")),
        taker_sell_volume=_number(payload.get("taker_sell_volume")),
        crowding_score=_number(payload.get("crowding_score")),
        crowding_label=payload.get("crowding_label"),
        crowding_reason=payload.get("crowding_reason"),
    )


def _shakeout_analysis_from_payload(payload: Any) -> ShakeoutAnalysis | None:
    if not isinstance(payload, dict):
        return None
    health = tuple(
        _stream_health_from_payload(item)
        for item in payload.get("stream_health", ())
        if isinstance(item, dict)
    )
    return ShakeoutAnalysis(
        status=str(payload.get("status", "N/A")),
        direction=str(payload.get("direction", "N/A")),
        score=_number(payload.get("score")) or 0.0,
        order_book_imbalance=_number(payload.get("order_book_imbalance")),
        bid_depth_usd=_number(payload.get("bid_depth_usd")),
        ask_depth_usd=_number(payload.get("ask_depth_usd")),
        taker_buy_usd=_number(payload.get("taker_buy_usd")) or 0.0,
        taker_sell_usd=_number(payload.get("taker_sell_usd")) or 0.0,
        large_trade_count=int(payload.get("large_trade_count") or 0),
        large_trade_net_usd=_number(payload.get("large_trade_net_usd")) or 0.0,
        liquidation_buy_usd=_number(payload.get("liquidation_buy_usd")) or 0.0,
        liquidation_sell_usd=_number(payload.get("liquidation_sell_usd")) or 0.0,
        liquidation_count=int(payload.get("liquidation_count") or 0),
        open_interest_change_percent=_number(
            payload.get("open_interest_change_percent")
        ),
        top_trader_long_short_ratio=_number(
            payload.get("top_trader_long_short_ratio")
        ),
        reason=str(payload.get("reason", "")),
        updated_at=(
            _parse_datetime(payload["updated_at"])
            if payload.get("updated_at")
            else None
        ),
        depth_stress_ratio=_number(payload.get("depth_stress_ratio")),
        taker_flow_stress_ratio=_number(payload.get("taker_flow_stress_ratio")),
        large_trade_stress_ratio=_number(payload.get("large_trade_stress_ratio")),
        liquidation_stress_ratio=_number(payload.get("liquidation_stress_ratio")),
        stream_health=health,
    )


def _stream_health_from_payload(payload: dict[str, Any]) -> MicrostructureStreamHealth:
    return MicrostructureStreamHealth(
        name=str(payload.get("name", "")),
        status=str(payload.get("status", "")),
        event_count=int(payload.get("event_count") or 0),
        last_event_at=(
            _parse_datetime(payload["last_event_at"])
            if payload.get("last_event_at")
            else None
        ),
        last_event_age_seconds=_number(payload.get("last_event_age_seconds")),
    )


def _window_label(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _compact_usd(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"
