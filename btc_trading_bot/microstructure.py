from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
            large_net=large_net,
            liq_imbalance=liq_imbalance,
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
        large_net: float,
        liq_imbalance: float | None,
        oi_change: float | None,
    ) -> tuple[float, float, list[str]]:
        upside = 0.0
        downside = 0.0
        reasons: list[str] = []

        if bid_depth is not None and ask_depth is not None and bid_depth > 0 and ask_depth > 0:
            if ask_depth < bid_depth * 0.65:
                upside += 0.22
                reasons.append("thin ask liquidity")
            if bid_depth < ask_depth * 0.65:
                downside += 0.22
                reasons.append("thin bid liquidity")
        if book_imbalance is not None and abs(book_imbalance) > 0.35:
            if book_imbalance > 0:
                upside += 0.08
            else:
                downside += 0.08

        if taker_imbalance is not None and abs(taker_imbalance) > 0.20:
            contribution = min(0.24, abs(taker_imbalance) * 0.24)
            if taker_imbalance > 0:
                upside += contribution
                reasons.append("aggressive buy flow")
            else:
                downside += contribution
                reasons.append("aggressive sell flow")

        if abs(large_net) >= self.settings.whale_trade_usd:
            contribution = min(0.18, abs(large_net) / (self.settings.whale_trade_usd * 8) * 0.18)
            if large_net > 0:
                upside += contribution
                reasons.append("large taker buys")
            else:
                downside += contribution
                reasons.append("large taker sells")

        if liq_imbalance is not None and abs(liq_imbalance) > 0.20:
            contribution = min(0.24, abs(liq_imbalance) * 0.24)
            if liq_imbalance > 0:
                upside += contribution
                reasons.append("short liquidation burst")
            else:
                downside += contribution
                reasons.append("long liquidation burst")

        ratio = self._top_trader_long_short_ratio
        if ratio is not None:
            if ratio >= 1.50:
                downside += 0.12
                reasons.append("top traders crowded long")
            elif ratio <= 0.75:
                upside += 0.12
                reasons.append("top traders crowded short")

        if oi_change is not None and abs(oi_change) >= 1.0:
            if oi_change > 0:
                upside += 0.05
                downside += 0.05
                reasons.append("open interest building")
            elif taker_imbalance is not None:
                if taker_imbalance > 0:
                    upside += 0.07
                elif taker_imbalance < 0:
                    downside += 0.07
                reasons.append("open interest flushing")

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
    if score >= 0.65:
        return "HIGH"
    if score >= 0.35:
        return "MEDIUM"
    if score >= 0.15:
        return "LOW"
    return "CALM"
