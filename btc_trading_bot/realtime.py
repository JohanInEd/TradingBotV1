from __future__ import annotations

import asyncio
import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp
import ccxt.pro as ccxtpro

from btc_trading_bot.config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: str
    received_at: datetime
    payload: Any = None
    timeframe: str | None = None
    message: str | None = None


class RealtimeMarketStream:
    def __init__(
        self,
        settings: Settings,
        exchange_id: str,
        *,
        symbol: str | None = None,
        exchange_options: dict[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.exchange_id = exchange_id
        self.symbol = symbol or settings.symbol
        self.exchange_options = exchange_options or {"defaultType": "spot"}
        self.events: queue.Queue[StreamEvent] = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="btc-market-stream",
            daemon=True,
        )
        self._thread.start()

    def drain(self) -> list[StreamEvent]:
        drained: list[StreamEvent] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            LOGGER.exception("Realtime market stream stopped")
            self._publish(
                StreamEvent(
                    kind="status",
                    received_at=datetime.now(timezone.utc),
                    message=f"WebSocket stopped: {exc}",
                )
            )

    async def _run(self) -> None:
        exchange_class = getattr(ccxtpro, self.exchange_id, None)
        if exchange_class is None:
            self._publish_status(
                f"WebSocket unavailable for {self.exchange_id}"
            )
            return

        connector = aiohttp.TCPConnector(
            resolver=aiohttp.ThreadedResolver(),
            enable_cleanup_closed=True,
        )
        session = aiohttp.ClientSession(
            connector=connector,
            trust_env=True,
        )
        exchange = exchange_class(
            {
                "enableRateLimit": True,
                "timeout": int(self.settings.request_timeout_seconds * 1000),
                "options": self.exchange_options,
                "session": session,
            }
        )
        tasks: list[asyncio.Task[None]] = []
        try:
            await exchange.load_markets()
            tasks.append(asyncio.create_task(self._watch_ticker(exchange)))
            for timeframe in {
                self.settings.timeframe,
                self.settings.daily_timeframe,
                self.settings.entry_timeframe,
                "30m",
            }:
                tasks.append(
                    asyncio.create_task(
                        self._watch_candles(exchange, timeframe)
                    )
                )
            if self.exchange_id == "binanceusdm":
                tasks.extend(self._binance_microstructure_tasks(session))
            self._publish_status("LIVE")
            while not self._stop.is_set():
                await asyncio.sleep(0.25)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await exchange.close()
            finally:
                await session.close()

    async def _watch_ticker(self, exchange: Any) -> None:
        if not exchange.has.get("watchTicker"):
            self._publish_status("Ticker WebSocket unsupported")
            return
        while not self._stop.is_set():
            try:
                ticker = await exchange.watch_ticker(self.symbol)
                self._publish(
                    StreamEvent(
                        kind="ticker",
                        received_at=datetime.now(timezone.utc),
                        payload=ticker,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._publish_status(f"Ticker reconnecting: {exc}")
                await asyncio.sleep(self.settings.stream_retry_seconds)

    async def _watch_candles(self, exchange: Any, timeframe: str) -> None:
        if not exchange.has.get("watchOHLCV"):
            self._publish_status("Candle WebSocket unsupported")
            return
        while not self._stop.is_set():
            try:
                rows = await exchange.watch_ohlcv(
                    self.symbol,
                    timeframe=timeframe,
                    limit=self.settings.candle_limit,
                )
                if rows:
                    self._publish(
                        StreamEvent(
                            kind="candle",
                            received_at=datetime.now(timezone.utc),
                            payload=rows[-1],
                            timeframe=timeframe,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._publish_status(
                    f"{timeframe} candles reconnecting: {exc}"
                )
                await asyncio.sleep(self.settings.stream_retry_seconds)

    def _binance_microstructure_tasks(
        self, session: aiohttp.ClientSession
    ) -> list[asyncio.Task[None]]:
        symbol = _binance_stream_symbol(self.symbol)
        return [
            asyncio.create_task(
                self._watch_binance_stream(
                    session,
                    "public",
                    {f"{symbol}@depth20@100ms": "depth"},
                )
            ),
            asyncio.create_task(
                self._watch_binance_stream(
                    session,
                    "market",
                    {
                        f"{symbol}@aggTrade": "trade",
                        f"{symbol}@forceOrder": "liquidation",
                    },
                )
            ),
        ]

    async def _watch_binance_stream(
        self,
        session: aiohttp.ClientSession,
        route: str,
        streams: dict[str, str],
    ) -> None:
        stream_names = "/".join(streams)
        url = f"wss://fstream.binance.com/{route}/stream?streams={stream_names}"
        while not self._stop.is_set():
            try:
                async with session.ws_connect(
                    url,
                    heartbeat=120,
                    receive_timeout=self.settings.stream_stale_seconds * 4,
                ) as websocket:
                    async for message in websocket:
                        if self._stop.is_set():
                            return
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json()
                            stream = payload.get("stream")
                            data = payload.get("data")
                            kind = streams.get(stream)
                            if kind is not None and data is not None:
                                self._publish(
                                    StreamEvent(
                                        kind=kind,
                                        received_at=datetime.now(timezone.utc),
                                        payload=data,
                                    )
                                )
                        elif message.type in {
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._publish_status(
                    f"Microstructure {route} reconnecting: {exc}"
                )
                await asyncio.sleep(self.settings.stream_retry_seconds)

    def _publish_status(self, message: str) -> None:
        self._publish(
            StreamEvent(
                kind="status",
                received_at=datetime.now(timezone.utc),
                message=message,
            )
        )

    def _publish(self, event: StreamEvent) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait(event)
            except queue.Full:
                LOGGER.warning("Dropping realtime event because queue is full")


def _binance_stream_symbol(symbol: str) -> str:
    market_symbol = symbol.split(":", maxsplit=1)[0]
    return market_symbol.replace("/", "").lower()
