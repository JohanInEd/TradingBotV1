from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from btc_trading_bot.app import (
    BotService,
    _apply_news_refresh,
    _apply_stream_events,
    _completed_health,
    _market_is_stale,
    next_analysis_boundary,
)
from btc_trading_bot.config import Settings
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.models import (
    Evaluation,
    FuturesMetrics,
    MacroAnalysis,
    RefreshHealth,
    SentimentAnalysis,
)
from btc_trading_bot.realtime import RealtimeMarketStream
from btc_trading_bot.strategy import calculate_signal

LOGGER = logging.getLogger(__name__)
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class WebStateService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.service = BotService(settings)
        self.stream: RealtimeMarketStream | None = None
        self.news_executor: ThreadPoolExecutor | None = None
        self.news_future: Future[
            tuple[
                SentimentAnalysis | None,
                MacroAnalysis | None,
                tuple[str, ...],
            ]
        ] | None = None
        self._condition = threading.Condition()
        self._evaluation: Evaluation | None = None
        self._version = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_market_refresh: datetime | None = None
        self._next_futures_refresh: datetime | None = None
        self._next_news_refresh: datetime | None = None
        self._next_analysis: datetime | None = None

    def start(self) -> None:
        evaluation = self.service.evaluate()
        now = datetime.now(timezone.utc)
        self._next_market_refresh = now + timedelta(
            seconds=self.settings.market_refresh_seconds
        )
        self._next_futures_refresh = now + timedelta(
            seconds=self.settings.market_refresh_seconds
        )
        self._next_news_refresh = now + timedelta(
            seconds=self.settings.news_refresh_seconds
        )
        self._next_analysis = evaluation.next_analysis_at
        evaluation = replace(
            evaluation,
            market_health=replace(
                evaluation.market_health,
                next_refresh_at=self._next_market_refresh,
            ),
            futures_health=replace(
                evaluation.futures_health,
                next_refresh_at=(
                    self._next_futures_refresh
                    if self.service.exchange.id == "binanceusdm"
                    else None
                ),
            ),
            news_health=replace(
                evaluation.news_health,
                next_refresh_at=self._next_news_refresh,
            ),
        )
        self._set_evaluation(evaluation)

        self.stream = RealtimeMarketStream(
            self.settings,
            self.service.exchange.id,
            symbol=self.service.exchange.symbol,
            exchange_options=self.service.exchange.options,
        )
        self.stream.start()
        self.news_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="btc-web-news"
        )
        self._thread = threading.Thread(
            target=self._run,
            name="btc-web-state",
            daemon=True,
        )
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return self._snapshot_locked()

    def wait_for_update(
        self, version: int, timeout: float = 15.0
    ) -> tuple[int, dict[str, Any]]:
        with self._condition:
            if self._version <= version:
                self._condition.wait_for(
                    lambda: self._version > version or self._stop.is_set(),
                    timeout=timeout,
                )
            return self._version, self._snapshot_locked()

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self.stream is not None:
            self.stream.close()
        if self.news_executor is not None:
            self.news_executor.shutdown(wait=True, cancel_futures=True)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self.service.close()

    def _set_evaluation(self, evaluation: Evaluation) -> None:
        with self._condition:
            self._evaluation = evaluation
            self._version += 1
            self._condition.notify_all()

    def _current_evaluation(self) -> Evaluation:
        with self._condition:
            if self._evaluation is None:
                raise RuntimeError("web state has not been initialized")
            return self._evaluation

    def _snapshot_locked(self) -> dict[str, Any]:
        if self._evaluation is None:
            return {
                "version": self._version,
                "status": "starting",
                "evaluation": None,
            }
        return {
            "version": self._version,
            "status": "ok",
            "evaluation": _jsonable(self._evaluation),
            "generated_at": _jsonable(datetime.now(timezone.utc)),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                LOGGER.exception("Web state refresh failed")
            time.sleep(0.25)

    def _tick(self) -> None:
        if (
            self.stream is None
            or self.news_executor is None
            or self._next_market_refresh is None
            or self._next_futures_refresh is None
            or self._next_news_refresh is None
            or self._next_analysis is None
        ):
            return

        now = datetime.now(timezone.utc)
        evaluation = _apply_stream_events(
            self._current_evaluation(), self.service, self.stream.drain()
        )

        if now >= self._next_analysis:
            try:
                technical = self.service.refresh_technicals()
                signal = calculate_signal(
                    technical,
                    evaluation.sentiment,
                    evaluation.macro,
                    self.settings,
                )
                evaluation = replace(
                    evaluation,
                    technical=technical,
                    live_technical=None,
                    signal=signal,
                    futures=build_futures_recommendation(
                        signal, evaluation.market, self.settings
                    ),
                    price_range=self.service.price_range,
                    market_context=self.service.market_context,
                    evaluated_at=now,
                )
                self._next_analysis = next_analysis_boundary(
                    now, self.settings.analysis_interval_hours
                )
            except Exception as exc:
                evaluation = _with_error(
                    evaluation, f"Analysis refresh failed: {exc}"
                )
                self._next_analysis = now + timedelta(minutes=5)

        if self.news_future is None and now >= self._next_news_refresh:
            self.news_future = self.news_executor.submit(
                self.service.refresh_news
            )
            self._next_news_refresh = now + timedelta(
                seconds=self.settings.news_refresh_seconds
            )
            evaluation = replace(
                evaluation,
                news_health=replace(
                    evaluation.news_health,
                    status="REFRESHING",
                    last_attempt_at=now,
                    next_refresh_at=self._next_news_refresh,
                    detail=None,
                ),
            )
        if self.news_future is not None and self.news_future.done():
            try:
                sentiment, macro, errors = self.news_future.result()
                evaluation = _apply_news_refresh(
                    evaluation,
                    sentiment,
                    macro,
                    errors,
                    self.settings,
                    now,
                )
            except Exception as exc:
                evaluation = _with_error(
                    evaluation, f"News refresh failed: {exc}"
                )
            self.news_future = None

        stream_is_stale = (
            evaluation.market.source == "WebSocket"
            and _market_is_stale(
                evaluation.market, now, self.settings.stream_stale_seconds
            )
        )
        if stream_is_stale or now >= self._next_market_refresh:
            if stream_is_stale or _market_is_stale(
                evaluation.market, now, self.settings.stream_stale_seconds
            ):
                try:
                    market = self.service.refresh_market()
                    evaluation = replace(
                        evaluation,
                        market=market,
                        stream_status="REST fallback",
                        market_health=RefreshHealth(
                            status="REST",
                            last_success_at=market.timestamp,
                            last_attempt_at=now,
                            next_refresh_at=self._next_market_refresh,
                        ),
                    )
                except Exception as exc:
                    evaluation = _with_error(
                        evaluation, f"Price refresh failed: {exc}"
                    )
                    evaluation = replace(
                        evaluation,
                        market_health=replace(
                            evaluation.market_health,
                            status="FAILED",
                            last_attempt_at=now,
                            detail=str(exc),
                        ),
                    )
            self._next_market_refresh = now + timedelta(
                seconds=self.settings.market_refresh_seconds
            )

        if (
            self.service.exchange.id == "binanceusdm"
            and now >= self._next_futures_refresh
        ):
            try:
                metrics, errors = self.service.refresh_futures_metrics()
                for error in errors:
                    evaluation = _with_error(evaluation, error)
                shakeout = self.service.apply_futures_metrics(metrics, now)
                evaluation = replace(
                    evaluation,
                    futures_metrics=metrics or evaluation.futures_metrics,
                    shakeout=shakeout,
                    futures_health=_completed_health(
                        evaluation.futures_health,
                        succeeded=metrics is not None,
                        errors=errors,
                        attempted_at=now,
                    ),
                )
            except Exception as exc:
                evaluation = _with_error(
                    evaluation, f"Futures metrics refresh failed: {exc}"
                )
                evaluation = replace(
                    evaluation,
                    futures_health=replace(
                        evaluation.futures_health,
                        status="FAILED",
                        last_attempt_at=now,
                        detail=str(exc),
                    ),
                )
            self._next_futures_refresh = now + timedelta(
                seconds=self.settings.market_refresh_seconds
            )

        evaluation = replace(
            evaluation,
            next_analysis_at=self._next_analysis,
            market_health=replace(
                evaluation.market_health,
                next_refresh_at=self._next_market_refresh,
            ),
            futures_health=replace(
                evaluation.futures_health,
                next_refresh_at=(
                    self._next_futures_refresh
                    if self.service.exchange.id == "binanceusdm"
                    else None
                ),
            ),
            news_health=replace(
                evaluation.news_health,
                next_refresh_at=self._next_news_refresh,
            ),
        )
        self._set_evaluation(evaluation)


class WebRequestHandler(BaseHTTPRequestHandler):
    server: "WebServer"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/snapshot":
            self._send_json(self.server.state.snapshot())
            return
        if path == "/api/stream":
            self._send_stream()
            return
        self._send_static(path)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        version = -1
        try:
            while not self.server.state._stop.is_set():
                next_version, payload = self.server.state.wait_for_update(
                    version, timeout=15.0
                )
                if next_version > version:
                    version = next_version
                    self._write_event("snapshot", payload)
                else:
                    self._write_event(
                        "heartbeat",
                        {"version": version, "status": "ok"},
                    )
        except (BrokenPipeError, ConnectionResetError):
            return

    def _write_event(self, event: str, payload: dict[str, Any]) -> None:
        body = (
            f"event: {event}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        ).encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def _send_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = WEB_DIST / "index.html"
        else:
            file_path = (WEB_DIST / path.lstrip("/")).resolve()

        try:
            file_path.relative_to(WEB_DIST.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if not file_path.exists() or not file_path.is_file():
            fallback = WEB_DIST / "index.html"
            if fallback.exists():
                file_path = fallback
            else:
                self._send_missing_frontend()
                return

        body = file_path.read_bytes()
        content_type = mimetypes.guess_type(file_path.name)[0]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_missing_frontend(self) -> None:
        body = (
            "<!doctype html><title>BTC Tri-Factor Web</title>"
            "<body style='font-family: system-ui; padding: 2rem'>"
            "<h1>BTC Tri-Factor Web API is running</h1>"
            "<p>Build the React UI with <code>cd web && npm install && "
            "npm run build</code>, or use <code>npm run dev</code> while "
            "this server is running.</p>"
            "<p>Live JSON is available at <a href='/api/snapshot'>"
            "/api/snapshot</a>.</p>"
            "</body>"
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, address: tuple[str, int], state: WebStateService
    ) -> None:
        super().__init__(address, WebRequestHandler)
        self.state = state


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _with_error(evaluation: Evaluation, message: str) -> Evaluation:
    errors = tuple(dict.fromkeys((*evaluation.errors, message)))
    return replace(evaluation, errors=errors[-5:])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the BTC Tri-Factor React dashboard and live API"
    )
    parser.add_argument(
        "--exchange",
        choices=("auto", "kraken", "binance", "binance-usdm"),
        help="Exchange to use (default: BOT_EXCHANGE or auto)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable diagnostic logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    if args.exchange:
        settings = replace(settings, exchange=args.exchange)

    state = WebStateService(settings)
    try:
        state.start()
        server = WebServer((args.host, args.port), state)
        print(
            f"BTC Tri-Factor web dashboard: http://{args.host}:{args.port}",
            flush=True,
        )
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.close()
        if "server" in locals():
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
