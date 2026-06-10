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
    def __init__(self, settings: Settings, exchange_id: str) -> None:
        self.settings = settings
        self.exchange_id = exchange_id
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
                "options": {"defaultType": "spot"},
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
            }:
                tasks.append(
                    asyncio.create_task(
                        self._watch_candles(exchange, timeframe)
                    )
                )
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
                ticker = await exchange.watch_ticker(self.settings.symbol)
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
                    self.settings.symbol,
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
