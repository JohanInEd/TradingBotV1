from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.models import FuturesMetrics, ShakeoutAnalysis


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


class ShakeoutMonitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._depth_bids: list[tuple[float, float]] = []
        self._depth_asks: list[tuple[float, float]] = []
        self._trades: deque[_FlowEvent] = deque()
        self._liquidations: deque[_FlowEvent] = deque()
        self._open_interest: deque[_OpenInterestSample] = deque(maxlen=20)
        self._top_trader_long_short_ratio: float | None = None
        self._updated_at: datetime | None = None

    def apply_depth(self, payload: dict[str, Any], received_at: datetime) -> ShakeoutAnalysis:
        self._depth_bids = _levels(payload.get("b"))
        self._depth_asks = _levels(payload.get("a"))
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
                    is_large=notional >= self.settings.whale_trade_usd,
                )
            )
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

        taker_buy = sum(event.notional for event in self._trades if event.side == "BUY")
        taker_sell = sum(event.notional for event in self._trades if event.side == "SELL")
        taker_imbalance = _imbalance(taker_buy, taker_sell)
        large_trades = [event for event in self._trades if event.is_large]
        large_net = sum(
            event.notional if event.side == "BUY" else -event.notional
            for event in large_trades
        )

        liq_buy = sum(
            event.notional for event in self._liquidations if event.side == "BUY"
        )
        liq_sell = sum(
            event.notional for event in self._liquidations if event.side == "SELL"
        )
        liq_imbalance = _imbalance(liq_buy, liq_sell)
        oi_change = self._open_interest_change_percent()

        upside, downside, reasons = self._score(
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            book_imbalance=book_imbalance,
            taker_imbalance=taker_imbalance,
            taker_total=taker_buy + taker_sell,
            large_net=large_net,
            liq_imbalance=liq_imbalance,
            liq_total=liq_buy + liq_sell,
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
        )

    def _score(
        self,
        *,
        bid_depth: float | None,
        ask_depth: float | None,
        book_imbalance: float | None,
        taker_imbalance: float | None,
        taker_total: float,
        large_net: float,
        liq_imbalance: float | None,
        liq_total: float,
        oi_change: float | None,
    ) -> tuple[float, float, list[str]]:
        upside = 0.0
        downside = 0.0
        reasons: list[str] = []
        window_label = _window_label(self.settings.shakeout_window_seconds)

        if bid_depth is not None and ask_depth is not None and bid_depth > 0 and ask_depth > 0:
            ask_ratio = ask_depth / bid_depth
            bid_ratio = bid_depth / ask_depth
            if ask_ratio < 0.45:
                upside += 0.30
                reasons.append(
                    f"thin ask liquidity ({_compact_usd(ask_depth)} ask vs {_compact_usd(bid_depth)} bid)"
                )
            elif ask_ratio < 0.70:
                upside += 0.20
                reasons.append(
                    f"thin ask liquidity ({_compact_usd(ask_depth)} ask vs {_compact_usd(bid_depth)} bid)"
                )
            if bid_ratio < 0.45:
                downside += 0.30
                reasons.append(
                    f"thin bid liquidity ({_compact_usd(bid_depth)} bid vs {_compact_usd(ask_depth)} ask)"
                )
            elif bid_ratio < 0.70:
                downside += 0.20
                reasons.append(
                    f"thin bid liquidity ({_compact_usd(bid_depth)} bid vs {_compact_usd(ask_depth)} ask)"
                )
        if book_imbalance is not None and abs(book_imbalance) > 0.40:
            if book_imbalance > 0:
                upside += 0.06
            else:
                downside += 0.06

        min_flow = self.settings.whale_trade_usd * 0.20
        if (
            taker_imbalance is not None
            and taker_total >= min_flow
            and abs(taker_imbalance) >= 0.25
        ):
            contribution = min(0.28, 0.10 + abs(taker_imbalance) * 0.18)
            net_flow = taker_total * abs(taker_imbalance)
            if taker_imbalance > 0:
                upside += contribution
                reasons.append(
                    f"aggressive buy flow ({_compact_usd(net_flow)} net over {window_label})"
                )
            else:
                downside += contribution
                reasons.append(
                    f"aggressive sell flow ({_compact_usd(net_flow)} net over {window_label})"
                )

        if abs(large_net) >= self.settings.whale_trade_usd:
            contribution = min(
                0.18,
                abs(large_net) / (self.settings.whale_trade_usd * 4) * 0.18,
            )
            if large_net > 0:
                upside += contribution
                reasons.append(f"large taker buys ({_compact_usd(abs(large_net))} net)")
            else:
                downside += contribution
                reasons.append(f"large taker sells ({_compact_usd(abs(large_net))} net)")

        min_liquidations = max(5_000.0, self.settings.whale_trade_usd * 0.05)
        if (
            liq_imbalance is not None
            and liq_total >= min_liquidations
            and abs(liq_imbalance) >= 0.25
        ):
            contribution = min(0.30, 0.10 + abs(liq_imbalance) * 0.20)
            net_liquidations = liq_total * abs(liq_imbalance)
            if liq_imbalance > 0:
                upside += contribution
                reasons.append(
                    f"short liquidation burst ({_compact_usd(net_liquidations)} over {window_label})"
                )
            else:
                downside += contribution
                reasons.append(
                    f"long liquidation burst ({_compact_usd(net_liquidations)} over {window_label})"
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

        return min(1.0, upside), min(1.0, downside), reasons[:5]

    def _open_interest_change_percent(self) -> float | None:
        if len(self._open_interest) < 2:
            return None
        first = self._open_interest[0].amount
        latest = self._open_interest[-1].amount
        if first <= 0:
            return None
        return (latest - first) / first * 100.0

    def _prune(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.settings.shakeout_window_seconds)
        for events in (self._trades, self._liquidations):
            while events and events[0].timestamp < cutoff:
                events.popleft()
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
    monitor = ShakeoutMonitor(settings)
    analyses: list[ShakeoutAnalysis] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            event = json.loads(line)
            kind = str(event.get("kind", ""))
            received_at = _parse_datetime(event.get("received_at"))
            payload = event.get("payload")
            if kind == "depth":
                analyses.append(monitor.apply_depth(payload, received_at))
            elif kind == "trade":
                analyses.append(monitor.apply_trade(payload, received_at))
            elif kind == "liquidation":
                analyses.append(monitor.apply_liquidation(payload, received_at))
            elif kind == "futures_metrics":
                analyses.append(
                    monitor.apply_futures_metrics(
                        _futures_metrics_from_payload(payload), received_at
                    )
                )
    return analyses


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
