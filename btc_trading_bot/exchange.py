from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import ccxt
import pandas as pd

from btc_trading_bot.config import Settings
from btc_trading_bot.models import MarketSnapshot

LOGGER = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    """Raised when usable market data cannot be obtained."""


@dataclass(frozen=True, slots=True)
class ExchangeSpec:
    ccxt_id: str
    symbol: str
    options: dict[str, str]


def resolve_exchange_spec(exchange_id: str, symbol: str) -> ExchangeSpec:
    if exchange_id in {"binance-usdm", "binanceusdm"}:
        return ExchangeSpec(
            ccxt_id="binanceusdm",
            symbol=_usdm_symbol(symbol),
            options={"defaultType": "future"},
        )
    return ExchangeSpec(
        ccxt_id=exchange_id,
        symbol=symbol,
        options={"defaultType": "spot"},
    )


class ExchangeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange: ccxt.Exchange
        self.spec: ExchangeSpec
        self.exchange = self._connect()

    @property
    def name(self) -> str:
        return self.exchange.name.replace("USD\u24c8-M", "USD-M")

    @property
    def id(self) -> str:
        spec = getattr(self, "spec", None)
        return spec.ccxt_id if spec is not None else self.exchange.id

    @property
    def symbol(self) -> str:
        spec = getattr(self, "spec", None)
        return spec.symbol if spec is not None else self.settings.symbol

    @property
    def options(self) -> dict[str, str]:
        spec = getattr(self, "spec", None)
        return dict(spec.options) if spec is not None else {"defaultType": "spot"}

    def _candidate_ids(self) -> tuple[str, ...]:
        if self.settings.exchange == "auto":
            return ("kraken", "binance")
        return (self.settings.exchange,)

    def _connect(self) -> ccxt.Exchange:
        failures: list[str] = []
        for exchange_id in self._candidate_ids():
            spec = resolve_exchange_spec(exchange_id, self.settings.symbol)
            exchange_class = getattr(ccxt, spec.ccxt_id, None)
            if exchange_class is None:
                failures.append(f"{spec.ccxt_id}: unsupported CCXT exchange")
                continue
            exchange = exchange_class(
                {
                    "enableRateLimit": True,
                    "timeout": int(self.settings.request_timeout_seconds * 1000),
                    "options": spec.options,
                }
            )
            try:
                self._retry(exchange.load_markets)
                if spec.symbol not in exchange.markets:
                    raise MarketDataError(f"{spec.symbol} is not listed")
                if not exchange.has.get("fetchOHLCV"):
                    raise MarketDataError("OHLCV is not supported")
                self.spec = spec
                LOGGER.info("Connected to %s", exchange.name)
                return exchange
            except Exception as exc:
                failures.append(f"{exchange_id}: {exc}")
                LOGGER.warning("Exchange connection failed: %s", failures[-1])
                exchange.close()
        raise MarketDataError("No exchange available: " + "; ".join(failures))

    def _retry(self, operation: Callable[[], Any]) -> Any:
        retryable = (
            ccxt.NetworkError,
            ccxt.RequestTimeout,
            ccxt.ExchangeNotAvailable,
            ccxt.DDoSProtection,
            ccxt.RateLimitExceeded,
        )
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                return operation()
            except retryable:
                if attempt == self.settings.max_retries:
                    raise
                time.sleep(2 ** (attempt - 1))

    def fetch_market_snapshot(self) -> MarketSnapshot:
        try:
            ticker = self._retry(
                lambda: self.exchange.fetch_ticker(self.symbol)
            )
            return market_snapshot_from_ticker(
                ticker,
                exchange=self.name,
                symbol=self.symbol,
                source="REST",
            )
        except (ccxt.BaseError, ValueError, TypeError) as exc:
            raise MarketDataError(f"Ticker request failed: {exc}") from exc

    def fetch_closed_candles(self, timeframe: str | None = None) -> pd.DataFrame:
        timeframe = timeframe or self.settings.timeframe
        try:
            rows = self._retry(
                lambda: self.exchange.fetch_ohlcv(
                    self.symbol,
                    timeframe=timeframe,
                    limit=self.settings.candle_limit,
                )
            )
        except ccxt.BaseError as exc:
            raise MarketDataError(f"{timeframe} OHLCV request failed: {exc}") from exc

        if not rows:
            raise MarketDataError(f"Exchange returned no {timeframe} OHLCV candles")

        frame = pd.DataFrame(
            rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        numeric_columns = ["open", "high", "low", "close", "volume"]
        frame[numeric_columns] = frame[numeric_columns].apply(
            pd.to_numeric, errors="coerce"
        )
        frame = frame.dropna().drop_duplicates("timestamp").sort_values("timestamp")

        try:
            timeframe_delta = timedelta(
                seconds=self.exchange.parse_timeframe(timeframe)
            )
        except (TypeError, ValueError) as exc:
            raise MarketDataError(f"Unsupported timeframe: {timeframe}") from exc
        now = datetime.now(timezone.utc)
        frame = frame[
            frame["timestamp"].apply(lambda value: value.to_pydatetime() + timeframe_delta)
            <= now
        ]
        if len(frame) < 60:
            raise MarketDataError(
                f"Only {len(frame)} closed {timeframe} candles available; "
                "at least 60 are required"
            )
        return frame.reset_index(drop=True)

    def close(self) -> None:
        close = getattr(self.exchange, "close", None)
        if callable(close):
            close()


def _first_number(values: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(values.get(key))
        if value is not None:
            return value
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usdm_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol
    if "/" not in symbol:
        return symbol
    base, quote = symbol.split("/", maxsplit=1)
    return f"{base}/{quote}:{quote}"


def market_snapshot_from_ticker(
    ticker: dict[str, Any],
    *,
    exchange: str,
    symbol: str,
    source: str,
) -> MarketSnapshot:
    price = _first_number(ticker, "last", "close", "bid", "ask")
    if price is None:
        raise MarketDataError("Ticker did not contain a current price")

    percentage = _number(ticker.get("percentage"))
    if percentage is None:
        open_price = _number(ticker.get("open"))
        percentage = (
            ((price - open_price) / open_price) * 100
            if open_price not in (None, 0)
            else None
        )

    return MarketSnapshot(
        exchange=exchange,
        symbol=symbol,
        price=price,
        change_24h=percentage,
        timestamp=datetime.now(timezone.utc),
        bid=_number(ticker.get("bid")),
        ask=_number(ticker.get("ask")),
        source=source,
    )


def merge_candle_update(
    candles: pd.DataFrame,
    row: list[Any] | tuple[Any, ...],
    limit: int,
) -> pd.DataFrame:
    if len(row) < 6:
        raise MarketDataError("OHLCV update did not contain six values")

    update = pd.DataFrame(
        [row[:6]],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    update["timestamp"] = pd.to_datetime(
        update["timestamp"], unit="ms", utc=True
    )
    numeric_columns = ["open", "high", "low", "close", "volume"]
    update[numeric_columns] = update[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    update = update.dropna()
    if update.empty:
        raise MarketDataError("OHLCV update contained invalid values")

    merged = pd.concat([candles, update], ignore_index=True)
    merged = (
        merged.drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .tail(limit)
    )
    return merged.reset_index(drop=True)
