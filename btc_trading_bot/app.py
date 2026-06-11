from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from rich.console import Console
from rich.live import Live

from btc_trading_bot.config import Settings
from btc_trading_bot.dashboard import build_dashboard, build_static_report
from btc_trading_bot.exchange import (
    ExchangeClient,
    market_snapshot_from_ticker,
    merge_candle_update,
)
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.indicators import analyze_multi_timeframe
from btc_trading_bot.models import (
    Evaluation,
    MacroAnalysis,
    MarketSnapshot,
    SentimentAnalysis,
    TechnicalAnalysis,
)
from btc_trading_bot.news import (
    NewsAnalyzer,
    NewsError,
    neutral_macro,
    neutral_sentiment,
)
from btc_trading_bot.realtime import RealtimeMarketStream, StreamEvent
from btc_trading_bot.strategy import calculate_signal

LOGGER = logging.getLogger(__name__)


class BotService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange = ExchangeClient(settings)
        self.news = NewsAnalyzer(settings)
        self._live_candles: dict[str, Any] = {}

    def evaluate(self, market: MarketSnapshot | None = None) -> Evaluation:
        errors: list[str] = []
        market = market or self.exchange.fetch_market_snapshot()
        technical = self.refresh_technicals()

        sentiment, macro, news_errors = self.refresh_news()
        errors.extend(news_errors)
        if sentiment is None or macro is None:
            sentiment = neutral_sentiment()
            macro = neutral_macro()

        signal = calculate_signal(technical, sentiment, macro, self.settings)
        evaluated_at = datetime.now(timezone.utc)
        return Evaluation(
            market=market,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            signal=signal,
            futures=build_futures_recommendation(
                signal, market, self.settings
            ),
            evaluated_at=evaluated_at,
            next_analysis_at=next_analysis_boundary(
                evaluated_at, self.settings.analysis_interval_hours
            ),
            errors=tuple(errors),
            news_updated_at=evaluated_at,
        )

    def refresh_technicals(self) -> TechnicalAnalysis:
        four_hour_candles = self.exchange.fetch_closed_candles(
            self.settings.timeframe
        )
        daily_candles = self.exchange.fetch_closed_candles(
            self.settings.daily_timeframe
        )
        hourly_candles = self.exchange.fetch_closed_candles(
            self.settings.entry_timeframe
        )
        self._live_candles = {
            self.settings.timeframe: four_hour_candles.copy(),
            self.settings.daily_timeframe: daily_candles.copy(),
            self.settings.entry_timeframe: hourly_candles.copy(),
        }
        return self._analyze_candles(self._live_candles)

    def apply_live_candle(
        self, timeframe: str, row: list[Any] | tuple[Any, ...]
    ) -> TechnicalAnalysis | None:
        candles = self._live_candles.get(timeframe)
        if candles is None:
            return None
        self._live_candles[timeframe] = merge_candle_update(
            candles, row, self.settings.candle_limit
        )
        return self._analyze_candles(self._live_candles)

    def _analyze_candles(
        self, candles: dict[str, Any]
    ) -> TechnicalAnalysis:
        return analyze_multi_timeframe(
            candles[self.settings.timeframe],
            candles[self.settings.daily_timeframe],
            candles[self.settings.entry_timeframe],
            primary_weight=self.settings.primary_timeframe_weight,
            daily_weight=self.settings.daily_timeframe_weight,
            hourly_weight=self.settings.entry_timeframe_weight,
        )

    def refresh_news(
        self,
    ) -> tuple[
        SentimentAnalysis | None,
        MacroAnalysis | None,
        tuple[str, ...],
    ]:
        try:
            headlines, feed_errors = self.news.fetch()
            sentiment = self.news.analyze_sentiment(headlines)
            macro = self.news.analyze_macro(headlines)
            return sentiment, macro, feed_errors
        except NewsError as exc:
            return None, None, (str(exc),)

    def refresh_market(self) -> MarketSnapshot:
        return self.exchange.fetch_market_snapshot()

    def close(self) -> None:
        self.news.close()
        self.exchange.close()


def next_analysis_boundary(now: datetime, interval_hours: int) -> datetime:
    now = now.astimezone(timezone.utc)
    boundary_hour = ((now.hour // interval_hours) + 1) * interval_hours
    boundary_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return boundary_day + timedelta(hours=boundary_hour)


def run(settings: Settings, once: bool = False) -> int:
    console = Console()
    service: BotService | None = None
    stream: RealtimeMarketStream | None = None
    news_executor: ThreadPoolExecutor | None = None
    news_future: Future[
        tuple[
            SentimentAnalysis | None,
            MacroAnalysis | None,
            tuple[str, ...],
        ]
    ] | None = None
    try:
        with console.status("[bold cyan]Connecting to exchange and analyzing markets..."):
            service = BotService(settings)
            evaluation = service.evaluate()
    except Exception as exc:
        console.print(f"[bold red]Startup failed:[/bold red] {exc}")
        LOGGER.exception("Startup failed")
        if service is not None:
            service.close()
        return 1

    if once:
        try:
            console.print(build_static_report(evaluation))
        finally:
            service.close()
        return 0

    stream = RealtimeMarketStream(
        settings,
        service.exchange.id,
        symbol=service.exchange.symbol,
        exchange_options=service.exchange.options,
    )
    stream.start()
    news_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="btc-news"
    )
    next_market_refresh = datetime.now(timezone.utc) + timedelta(
        seconds=settings.market_refresh_seconds
    )
    next_news_refresh = datetime.now(timezone.utc) + timedelta(
        seconds=settings.news_refresh_seconds
    )
    next_analysis = evaluation.next_analysis_at

    try:
        with Live(
            build_dashboard(evaluation),
            console=console,
            screen=True,
            refresh_per_second=1,
        ) as live:
            while True:
                now = datetime.now(timezone.utc)
                evaluation = _apply_stream_events(
                    evaluation, service, stream.drain()
                )

                if now >= next_analysis:
                    try:
                        technical = service.refresh_technicals()
                        signal = calculate_signal(
                            technical,
                            evaluation.sentiment,
                            evaluation.macro,
                            settings,
                        )
                        evaluation = replace(
                            evaluation,
                            technical=technical,
                            live_technical=None,
                            signal=signal,
                            futures=build_futures_recommendation(
                                signal, evaluation.market, settings
                            ),
                            evaluated_at=now,
                        )
                        next_analysis = next_analysis_boundary(
                            now, settings.analysis_interval_hours
                        )
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation, f"Analysis refresh failed: {exc}"
                        )
                        next_analysis = now + timedelta(minutes=5)

                if news_future is None and now >= next_news_refresh:
                    news_future = news_executor.submit(service.refresh_news)
                    next_news_refresh = now + timedelta(
                        seconds=settings.news_refresh_seconds
                    )
                if news_future is not None and news_future.done():
                    try:
                        sentiment, macro, errors = news_future.result()
                        evaluation = _apply_news_refresh(
                            evaluation,
                            sentiment,
                            macro,
                            errors,
                            settings,
                            now,
                        )
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation, f"News refresh failed: {exc}"
                        )
                    news_future = None

                stream_is_stale = (
                    evaluation.market.source == "WebSocket"
                    and _market_is_stale(
                        evaluation.market,
                        now,
                        settings.stream_stale_seconds,
                    )
                )
                if stream_is_stale or now >= next_market_refresh:
                    if stream_is_stale or _market_is_stale(
                        evaluation.market,
                        now,
                        settings.stream_stale_seconds,
                    ):
                        try:
                            market = service.refresh_market()
                            evaluation = replace(
                                evaluation,
                                market=market,
                                stream_status="REST fallback",
                            )
                        except Exception as exc:
                            evaluation = _with_error(
                                evaluation, f"Price refresh failed: {exc}"
                            )
                    next_market_refresh = now + timedelta(
                        seconds=settings.market_refresh_seconds
                    )

                evaluation = replace(evaluation, next_analysis_at=next_analysis)
                live.update(build_dashboard(evaluation))
                time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        if stream is not None:
            stream.close()
        if news_executor is not None:
            news_executor.shutdown(wait=True, cancel_futures=True)
        if service is not None:
            service.close()


def _with_error(evaluation: Evaluation, message: str) -> Evaluation:
    errors = tuple(dict.fromkeys((*evaluation.errors, message)))
    return replace(evaluation, errors=errors[-5:])


def _apply_stream_events(
    evaluation: Evaluation,
    service: BotService,
    events: list[StreamEvent],
) -> Evaluation:
    current = evaluation
    for event in events:
        if event.kind == "ticker":
            try:
                market = market_snapshot_from_ticker(
                    event.payload,
                    exchange=service.exchange.name,
                    symbol=service.exchange.symbol,
                    source="WebSocket",
                )
                current = replace(
                    current,
                    market=market,
                    stream_status="LIVE",
                    stream_updated_at=event.received_at,
                )
            except Exception as exc:
                current = _with_error(
                    current, f"Live ticker update failed: {exc}"
                )
        elif event.kind == "candle" and event.timeframe is not None:
            try:
                live_technical = service.apply_live_candle(
                    event.timeframe, event.payload
                )
                current = replace(
                    current,
                    live_technical=live_technical,
                    stream_status="LIVE",
                    stream_updated_at=event.received_at,
                )
            except Exception as exc:
                current = _with_error(
                    current,
                    f"Live {event.timeframe} candle failed: {exc}",
                )
        elif event.kind == "status" and event.message:
            if event.message == "LIVE":
                current = replace(current, stream_status="LIVE")
            else:
                current = _with_error(current, event.message)
                current = replace(current, stream_status="RECONNECTING")
    return current


def _apply_news_refresh(
    evaluation: Evaluation,
    sentiment: SentimentAnalysis | None,
    macro: MacroAnalysis | None,
    errors: tuple[str, ...],
    settings: Settings,
    updated_at: datetime,
) -> Evaluation:
    current = evaluation
    for error in errors:
        current = _with_error(current, error)
    if sentiment is None or macro is None:
        return current

    signal = calculate_signal(
        current.technical, sentiment, macro, settings
    )
    return replace(
        current,
        sentiment=sentiment,
        macro=macro,
        signal=signal,
        futures=build_futures_recommendation(
            signal, current.market, settings
        ),
        evaluated_at=updated_at,
        news_updated_at=updated_at,
    )


def _market_is_stale(
    market: MarketSnapshot,
    now: datetime,
    stale_seconds: int,
) -> bool:
    return (now - market.timestamp).total_seconds() >= stale_seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BTC/USDT 4h tri-factor terminal signal bot"
    )
    parser.add_argument(
        "--exchange",
        choices=("auto", "kraken", "binance", "binance-usdm"),
        help="Exchange to use (default: BOT_EXCHANGE or auto)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Evaluate once, print the dashboard, and exit",
    )
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
    raise SystemExit(run(settings, once=args.once))


if __name__ == "__main__":
    main()
