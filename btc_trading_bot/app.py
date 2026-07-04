from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from rich.console import Console
from rich.live import Live

from btc_trading_bot.active_trader import ACTIVE_TRADER_TIMEFRAME, ActiveTrader
from btc_trading_bot.adaptive import resolve_signal_profile
from btc_trading_bot.backtest import (
    ProbabilityBacktestError,
    ProbabilityBacktestSettings,
    forecast_probability,
)
from btc_trading_bot.config import Settings
from btc_trading_bot.dashboard import build_dashboard, build_static_report
from btc_trading_bot.exchange import (
    ExchangeClient,
    market_snapshot_from_ticker,
    merge_candle_update,
)
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.history import HistoryStore, recent_contiguous_candles
from btc_trading_bot.indicators import (
    analyze_multi_timeframe,
    analyze_technicals,
    build_chart_indicators,
)
from btc_trading_bot.market_context import analyze_market_context
from btc_trading_bot.meta_model import MetaModel, assess_meta_model, train_meta_model
from btc_trading_bot.models import (
    ActiveTraderSnapshot,
    Evaluation,
    FuturesMetrics,
    FuturesRecommendation,
    MacroAnalysis,
    MarketSnapshot,
    MetaModelAssessment,
    PortfolioDecision,
    PortfolioState,
    RefreshHealth,
    ScalpingEvaluation,
    SentimentAnalysis,
    TechnicalAnalysis,
)
from btc_trading_bot.microstructure import ShakeoutEventRecorder, ShakeoutMonitor
from btc_trading_bot.news import (
    NewsAnalyzer,
    NewsError,
    blend_derivatives_crowding,
    neutral_macro,
    neutral_sentiment,
)
from btc_trading_bot.paper_setups import (
    PaperSetupJournal,
    PaperSetupReport,
    analyze_setup_rows,
    build_current_paper_setup,
)
from btc_trading_bot.portfolio import (
    build_portfolio_state,
    check_portfolio_entry,
    empty_portfolio_state,
)
from btc_trading_bot.price_range import PriceRangeSettings, forecast_price_range
from btc_trading_bot.realtime import RealtimeMarketStream, StreamEvent
from btc_trading_bot.risk_filters import apply_do_not_trade_filters
from btc_trading_bot.scalping import (
    SCALPING_TIMEFRAME,
    evaluate_scalping,
    finalize_execution_cycle,
    scalping_settings,
    to_journal_evaluation,
)
from btc_trading_bot.scenario_map import ScenarioMapSettings, forecast_scenario_map
from btc_trading_bot.scanner import MarketScanner
from btc_trading_bot.signal_journal import SignalJournalRecorder
from btc_trading_bot.strategy import calculate_signal

LOGGER = logging.getLogger(__name__)
TRADE_MODE_TIMEFRAMES = ("4h", "1h", "30m", "5m")


class BotService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.exchange = ExchangeClient(settings)
        self.news = NewsAnalyzer(settings)
        self._live_candles: dict[str, Any] = {}
        self._price_range = None
        self._probability_forecast = None
        self._scenario_forecast = None
        self._market_context = None
        self._trade_mode_contexts: dict[str, dict[str, Any]] = {}
        self.shakeout = ShakeoutMonitor(settings)
        self._shakeout_recorder = (
            ShakeoutEventRecorder(settings.shakeout_event_log_path)
            if settings.shakeout_event_log_path is not None
            else None
        )
        self._signal_journal = (
            SignalJournalRecorder(settings.signal_journal_path)
            if settings.signal_journal_path is not None
            else None
        )
        self._paper_setup_journal = (
            PaperSetupJournal(
                settings.paper_setup_journal_path,
                horizon_hours=settings.paper_setup_horizon_hours,
            )
            if settings.paper_setup_journal_path is not None
            else None
        )
        self.scanner = MarketScanner(settings, journal=self._paper_setup_journal)
        self._paper_setup_report: PaperSetupReport | None = None
        self._portfolio_state: PortfolioState = empty_portfolio_state(settings)
        self._meta_model: MetaModel | None = None
        self._signal_settings, self._signal_profile = resolve_signal_profile(
            settings, None
        )
        self._refresh_paper_setup_report()
        self._scalping_journal = (
            PaperSetupJournal(
                settings.scalping_journal_path,
                horizon_hours=settings.scalping_horizon_hours,
            )
            if settings.scalping_enabled and settings.scalping_journal_path is not None
            else None
        )
        self._scalping_report: PaperSetupReport | None = None
        self._refresh_scalping_report()
        self._active_trader = (
            ActiveTrader(settings) if settings.active_trader_enabled else None
        )

    def signal_settings(self) -> Settings:
        return self._signal_settings

    def signal_profile(self):
        return self._signal_profile

    def evaluate(self, market: MarketSnapshot | None = None) -> Evaluation:
        errors: list[str] = []
        market = market or self.exchange.fetch_market_snapshot()
        technical = self.refresh_technicals()

        sentiment, macro, news_errors = self.refresh_news()
        errors.extend(news_errors)
        news_succeeded = sentiment is not None and macro is not None
        if sentiment is None or macro is None:
            sentiment = neutral_sentiment()
            macro = neutral_macro()

        futures_metrics, futures_errors = self.refresh_futures_metrics()
        errors.extend(futures_errors)
        shakeout = self.apply_futures_metrics(
            futures_metrics, datetime.now(timezone.utc)
        )
        sentiment = blend_derivatives_crowding(sentiment, futures_metrics)
        evaluated_at = datetime.now(timezone.utc)
        signal = calculate_signal(technical, sentiment, macro, self.signal_settings())
        futures, trade_filter, portfolio, meta = self.build_futures_plan(
            signal,
            market,
            probability_forecast=self._probability_forecast,
            market_context=self._market_context,
            shakeout=shakeout,
            futures_metrics=futures_metrics,
            technical=technical,
        )
        paper_setup = build_current_paper_setup(
            futures=futures,
            technical=technical,
            evaluated_at=evaluated_at,
            settings=self.settings,
            market_context=self._market_context,
            probability_forecast=self._probability_forecast,
        )
        evaluation = Evaluation(
            market=market,
            technical=technical,
            sentiment=sentiment,
            macro=macro,
            signal=signal,
            futures=futures,
            trade_filter=trade_filter,
            paper_setup=paper_setup,
            evaluated_at=evaluated_at,
            next_analysis_at=next_analysis_boundary(
                evaluated_at, self.settings.analysis_interval_hours
            ),
            errors=tuple(errors),
            news_updated_at=evaluated_at if news_succeeded else None,
            futures_metrics=futures_metrics,
            price_range=self._price_range,
            probability_forecast=self._probability_forecast,
            scenario_forecast=self._scenario_forecast,
            market_context=self._market_context,
            shakeout=shakeout,
            market_health=RefreshHealth(
                status="OK",
                last_success_at=market.timestamp,
                last_attempt_at=evaluated_at,
            ),
            futures_health=_initial_futures_health(
                self.exchange.id,
                futures_metrics,
                futures_errors,
                evaluated_at,
            ),
            news_health=_completed_health(
                RefreshHealth(),
                succeeded=news_succeeded,
                errors=news_errors,
                attempted_at=evaluated_at,
            ),
            portfolio=portfolio,
            signal_profile=self.signal_profile(),
            meta=meta,
        )
        self.record_signal_evaluation(evaluation)
        self.record_paper_setup(evaluation)
        # The scanner allocates the remaining portfolio budget after the
        # primary setup has been recorded.
        scanner_result = self.refresh_scanner(sentiment, macro)
        return replace(evaluation, scanner=scanner_result)

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

        for timeframe in TRADE_MODE_TIMEFRAMES:
            if timeframe not in self._live_candles:
                try:
                    self._live_candles[timeframe] = self.exchange.fetch_closed_candles(
                        timeframe
                    )
                except Exception as exc:
                    LOGGER.warning("%s candle history unavailable: %s", timeframe, exc)

        self._refresh_trade_mode_contexts()
        primary_context = self._trade_mode_contexts.get(self.settings.timeframe, {})
        self._price_range = primary_context.get("price_range")
        self._probability_forecast = primary_context.get("probability_forecast")
        self._scenario_forecast = primary_context.get("scenario_forecast")
        self._market_context = primary_context.get("market_context")
        self.resolve_paper_setups(four_hour_candles)
        return self._analyze_candles(self._live_candles)

    @property
    def price_range(self):
        return self._price_range

    @property
    def probability_forecast(self):
        return self._probability_forecast

    @property
    def scenario_forecast(self):
        return self._scenario_forecast

    @property
    def market_context(self):
        return self._market_context

    def chart_data(self, limit: int = 120) -> dict[str, Any]:
        candles = self._live_candles.get(self.settings.timeframe)
        if candles is None:
            return {"timeframe": self.settings.timeframe, "candles": []}
        return {
            "timeframe": self.settings.timeframe,
            "candles": build_chart_indicators(candles, limit=limit),
        }

    def trade_modes(
        self,
        evaluation: Evaluation,
        *,
        limit: int = 180,
    ) -> dict[str, Any]:
        modes: dict[str, Any] = {}
        for timeframe in TRADE_MODE_TIMEFRAMES:
            candles = self._live_candles.get(timeframe)
            context = self._trade_mode_contexts.get(timeframe)
            if candles is None or context is None:
                modes[timeframe] = {
                    "timeframe": timeframe,
                    "label": _timeframe_label(timeframe),
                    "available": False,
                    "chart": {"timeframe": timeframe, "candles": []},
                    "error": "Candle history is not available yet.",
                }
                continue

            technical = context.get("technical")
            if technical is None:
                modes[timeframe] = {
                    "timeframe": timeframe,
                    "label": _timeframe_label(timeframe),
                    "available": False,
                    "chart": {
                        "timeframe": timeframe,
                        "candles": build_chart_indicators(candles, limit=limit),
                    },
                    "error": "Technical indicators are not available yet.",
                }
                continue

            mode_settings, mode_profile = resolve_signal_profile(
                self.settings, context.get("market_context")
            )
            signal = calculate_signal(
                technical,
                evaluation.sentiment,
                evaluation.macro,
                mode_settings,
            )
            futures, trade_filter, portfolio, meta = self.build_futures_plan(
                signal,
                evaluation.market,
                probability_forecast=context.get("probability_forecast"),
                market_context=context.get("market_context"),
                shakeout=evaluation.shakeout,
                futures_metrics=evaluation.futures_metrics,
                technical=technical,
            )
            paper_setup = build_current_paper_setup(
                futures=futures,
                technical=technical,
                evaluated_at=evaluation.evaluated_at,
                settings=self.settings,
                market_context=context.get("market_context"),
                probability_forecast=context.get("probability_forecast"),
            )
            modes[timeframe] = {
                "timeframe": timeframe,
                "label": _timeframe_label(timeframe),
                "available": True,
                "chart": {
                    "timeframe": timeframe,
                    "candles": build_chart_indicators(candles, limit=limit),
                },
                "technical": technical,
                "signal": signal,
                "signal_profile": mode_profile,
                "futures": futures,
                "trade_filter": trade_filter,
                "portfolio": portfolio,
                "meta": meta,
                "paper_setup": paper_setup,
                "price_range": context.get("price_range"),
                "probability_forecast": context.get("probability_forecast"),
                "scenario_forecast": context.get("scenario_forecast"),
                "market_context": context.get("market_context"),
            }
        return {
            "selected": self.settings.timeframe,
            "options": tuple(
                {"timeframe": timeframe, "label": _timeframe_label(timeframe)}
                for timeframe in TRADE_MODE_TIMEFRAMES
            ),
            "modes": modes,
        }

    def build_futures_plan(
        self,
        signal,
        market: MarketSnapshot,
        *,
        probability_forecast=None,
        market_context=None,
        shakeout=None,
        futures_metrics=None,
        technical=None,
    ):
        futures = build_futures_recommendation(signal, market, self.settings)
        futures, trade_filter = apply_do_not_trade_filters(
            futures,
            self.settings,
            probability_forecast=probability_forecast,
            market_context=market_context,
            shakeout=shakeout,
            futures_metrics=futures_metrics,
        )
        meta: MetaModelAssessment | None = None
        if futures.side in {"LONG", "SHORT"}:
            meta = assess_meta_model(
                self._meta_model,
                settings=self.settings,
                side=futures.side,
                technical=technical,
                market_context=market_context,
                probability_forecast=probability_forecast,
            )
            if meta.status == "BLOCKED":
                futures = _flatten_futures(
                    futures,
                    f"Meta model blocked {futures.action}: {meta.detail}",
                )
        portfolio: PortfolioDecision | None = None
        if futures.side in {"LONG", "SHORT"}:
            portfolio = check_portfolio_entry(
                self.portfolio_state(),
                symbol=self.exchange.symbol,
                side=futures.side,
                max_loss=futures.max_loss,
                settings=self.settings,
                candle_time=(
                    technical.candle_time if technical is not None else None
                ),
            )
            if not portfolio.allowed:
                futures = _flatten_futures(
                    futures,
                    f"Portfolio limits blocked {futures.action}: "
                    + " ".join(portfolio.reasons),
                )
        return futures, trade_filter, portfolio, meta

    def portfolio_state(self) -> PortfolioState:
        return self._portfolio_state

    def paper_setup_report(self) -> PaperSetupReport | None:
        return self._paper_setup_report

    def apply_live_candle(
        self, timeframe: str, row: list[Any] | tuple[Any, ...]
    ) -> TechnicalAnalysis | None:
        candles = self._live_candles.get(timeframe)
        if candles is None:
            return None
        self._live_candles[timeframe] = merge_candle_update(
            candles, row, self.settings.candle_limit
        )
        if timeframe == self.settings.timeframe:
            self._market_context = analyze_market_context(
                self._live_candles[timeframe]
            )
        technical = self._analyze_candles(self._live_candles)
        if timeframe in TRADE_MODE_TIMEFRAMES:
            self._trade_mode_contexts[timeframe] = self._build_trade_mode_context(
                timeframe,
                self._live_candles[timeframe],
            )
        return technical

    def _analyze_candles(
        self, candles: dict[str, Any]
    ) -> TechnicalAnalysis:
        self._signal_settings, self._signal_profile = resolve_signal_profile(
            self.settings, self._market_context
        )
        return analyze_multi_timeframe(
            candles[self.settings.timeframe],
            candles[self.settings.daily_timeframe],
            candles[self.settings.entry_timeframe],
            primary_weight=self._signal_settings.primary_timeframe_weight,
            daily_weight=self._signal_settings.daily_timeframe_weight,
            hourly_weight=self._signal_settings.entry_timeframe_weight,
        )

    def _refresh_trade_mode_contexts(self) -> None:
        self._trade_mode_contexts = {
            timeframe: self._build_trade_mode_context(timeframe, candles)
            for timeframe, candles in self._live_candles.items()
            if timeframe in TRADE_MODE_TIMEFRAMES
        }

    def _build_trade_mode_context(
        self,
        timeframe: str,
        candles: Any,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {"timeframe": timeframe}
        try:
            context["technical"] = analyze_technicals(candles)
        except Exception as exc:
            LOGGER.warning("%s technical analysis unavailable: %s", timeframe, exc)
            context["technical"] = None

        price_range_horizon = _horizon_candles(
            self.settings.price_range_horizon_hours,
            timeframe,
        )
        try:
            price_range = forecast_price_range(
                candles,
                PriceRangeSettings(
                    horizon_hours=self.settings.price_range_horizon_hours,
                    horizon_candles=price_range_horizon,
                    lookback_candles=self.settings.price_range_lookback_candles,
                ),
            )
            context["price_range"] = replace(
                price_range,
                method=price_range.method.replace("4h candles", f"{timeframe} candles"),
            )
        except Exception as exc:
            LOGGER.warning("%s price range unavailable: %s", timeframe, exc)
            context["price_range"] = None

        probability_horizon = _horizon_candles(
            self.settings.probability_horizon_hours,
            timeframe,
        )
        try:
            probability = forecast_probability(
                _probability_candles_for_backtest(
                    self.settings,
                    self.exchange.id,
                    self.exchange.symbol,
                    candles,
                    timeframe=timeframe,
                    horizon_candles=probability_horizon,
                ),
                ProbabilityBacktestSettings(
                    horizon_hours=self.settings.probability_horizon_hours,
                    horizon_candles=probability_horizon,
                    lookback_candles=self.settings.probability_lookback_candles,
                    min_samples=self.settings.probability_min_samples,
                    max_samples=self.settings.probability_max_samples,
                ),
                stop_loss_percent=self.settings.stop_loss_percent,
                reward_to_risk=self.settings.reward_to_risk,
            )
            context["probability_forecast"] = replace(
                probability,
                method=probability.method.replace("4h technical", f"{timeframe} technical"),
            )
        except ProbabilityBacktestError as exc:
            LOGGER.warning("%s probability backtest unavailable: %s", timeframe, exc)
            context["probability_forecast"] = None

        scenario_horizon_hours = 1 if timeframe == "5m" else 168
        scenario_horizon = _horizon_candles(scenario_horizon_hours, timeframe)
        try:
            scenario = forecast_scenario_map(
                _probability_candles_for_backtest(
                    self.settings,
                    self.exchange.id,
                    self.exchange.symbol,
                    candles,
                    timeframe=timeframe,
                    horizon_candles=scenario_horizon,
                ),
                ScenarioMapSettings(
                    horizon_hours=scenario_horizon_hours,
                    horizon_candles=scenario_horizon,
                    lookback_candles=max(
                        220, self.settings.probability_lookback_candles
                    ),
                    min_samples=self.settings.probability_min_samples,
                    max_samples=self.settings.probability_max_samples,
                ),
            )
            context["scenario_forecast"] = (
                replace(
                    scenario,
                    method=scenario.method.replace("4h technical", f"{timeframe} technical"),
                )
                if scenario is not None
                else None
            )
        except Exception as exc:
            LOGGER.warning("%s scenario map unavailable: %s", timeframe, exc)
            context["scenario_forecast"] = None

        try:
            context["market_context"] = analyze_market_context(candles)
        except Exception as exc:
            LOGGER.warning("%s market context unavailable: %s", timeframe, exc)
            context["market_context"] = None

        return context

    def refresh_news(
        self,
    ) -> tuple[
        SentimentAnalysis | None,
        MacroAnalysis | None,
        tuple[str, ...],
    ]:
        try:
            headlines, feed_errors = self.news.fetch()
            sources, source_errors = self.news.fetch_sentiment_sources()
            calendar = self.news.analyze_economic_calendar()
            sentiment = self.news.analyze_sentiment(headlines, sources=sources)
            macro = self.news.analyze_macro(headlines, calendar=calendar)
            return sentiment, macro, (*feed_errors, *source_errors)
        except NewsError as exc:
            return None, None, (str(exc),)

    def refresh_market(self) -> MarketSnapshot:
        return self.exchange.fetch_market_snapshot()

    def refresh_scanner(
        self,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
    ):
        result = self.scanner.scan(
            sentiment,
            macro,
            portfolio_state=self.portfolio_state(),
            primary_symbol=self.exchange.symbol,
        )
        if self._paper_setup_journal is not None:
            # Scanner scans may have recorded or resolved setups.
            self._refresh_paper_setup_report()
        return result

    def refresh_futures_metrics(
        self,
    ) -> tuple[FuturesMetrics | None, tuple[str, ...]]:
        return self.exchange.fetch_futures_metrics()

    def apply_microstructure(
        self, kind: str, payload: Any, received_at: datetime
    ):
        if kind == "depth":
            analysis = self.shakeout.apply_depth(payload, received_at)
        elif kind == "trade":
            analysis = self.shakeout.apply_trade(payload, received_at)
        elif kind == "liquidation":
            analysis = self.shakeout.apply_liquidation(payload, received_at)
        else:
            analysis = self.shakeout.analyze(received_at)
        self._record_shakeout(kind, payload, received_at, analysis)
        return analysis

    def apply_futures_metrics(
        self, metrics: FuturesMetrics | None, received_at: datetime
    ):
        analysis = self.shakeout.apply_futures_metrics(metrics, received_at)
        self._record_shakeout("futures_metrics", metrics, received_at, analysis)
        return analysis

    def _record_shakeout(
        self,
        kind: str,
        payload: Any,
        received_at: datetime,
        analysis: Any,
    ) -> None:
        if self._shakeout_recorder is None:
            return
        self._shakeout_recorder.record(
            kind=kind,
            payload=payload,
            received_at=received_at,
            analysis=analysis,
        )

    def record_signal_evaluation(self, evaluation: Evaluation) -> None:
        if self._signal_journal is None:
            return
        try:
            self._signal_journal.record(
                evaluation,
                exchange=self.exchange.id,
                symbol=self.exchange.symbol,
                timeframe=self.settings.timeframe,
                settings=self.settings,
            )
        except Exception as exc:
            LOGGER.warning("Signal journal write failed: %s", exc)

    def record_paper_setup(self, evaluation: Evaluation) -> None:
        if self._paper_setup_journal is None:
            return
        if evaluation.portfolio is not None and evaluation.portfolio.status == "TRACKED":
            # This closed-candle setup is already the tracked open position;
            # re-recording would create a near-duplicate row.
            return
        try:
            self._paper_setup_journal.record(
                evaluation,
                exchange=self.exchange.id,
                symbol=self.exchange.symbol,
                timeframe=self.settings.timeframe,
                settings=self.settings,
            )
            self._refresh_paper_setup_report()
        except Exception as exc:
            LOGGER.warning("Paper setup journal write failed: %s", exc)

    def resolve_paper_setups(self, candles: Any) -> None:
        if self._paper_setup_journal is None:
            return
        try:
            self._paper_setup_journal.resolve_with_candles(
                candles,
                exchange=self.exchange.id,
                symbol=self.exchange.symbol,
                timeframe=self.settings.timeframe,
            )
            self._refresh_paper_setup_report()
        except Exception as exc:
            LOGGER.warning("Paper setup outcome resolution failed: %s", exc)

    def _refresh_paper_setup_report(self) -> None:
        if self._paper_setup_journal is None:
            return
        try:
            rows = self._paper_setup_journal.load_setups()
            self._paper_setup_report = analyze_setup_rows(
                rows,
                settings=self.settings,
            )
            self._portfolio_state = build_portfolio_state(
                rows, settings=self.settings
            )
            if self.settings.meta_model_enabled:
                self._meta_model = train_meta_model(
                    rows,
                    min_samples=self.settings.meta_min_training_samples,
                )
        except Exception as exc:
            LOGGER.warning("Paper setup report refresh failed: %s", exc)

    def journal_rows(self) -> list[dict[str, Any]]:
        if self._paper_setup_journal is None:
            return []
        try:
            return self._paper_setup_journal.load_setups()
        except Exception as exc:
            LOGGER.warning("Paper setup journal read failed: %s", exc)
            return []

    def refresh_scalping(self) -> ScalpingEvaluation | None:
        """Evaluate the closed-5m-candle scalping signal independently of the
        primary 4h-anchored signal, and journal it separately so it never
        shares portfolio limits or meta-model training with the main system.
        """
        if not self.settings.scalping_enabled:
            return None
        candles = self.exchange.fetch_closed_candles(SCALPING_TIMEFRAME)
        market = self.exchange.fetch_market_snapshot()
        shakeout = self.shakeout.analyze(datetime.now(timezone.utc))
        result = evaluate_scalping(candles, market, self.settings, shakeout=shakeout)

        if result.futures.side in {"LONG", "SHORT"}:
            fill_detail = (
                f"Paper-filled {result.paper_setup.side} at "
                f"${result.paper_setup.entry_price:,.2f}."
                if result.paper_setup is not None
                else "Paper setup filled."
            )
            if self._scalping_journal is not None:
                try:
                    self._scalping_journal.resolve_with_candles(
                        candles,
                        exchange=self.exchange.id,
                        symbol=self.exchange.symbol,
                        timeframe=SCALPING_TIMEFRAME,
                    )
                except Exception as exc:
                    LOGGER.warning("Scalping outcome resolution failed: %s", exc)

                if self._has_open_scalp():
                    already_open = "A scalp paper setup for this symbol is already open."
                    result = replace(
                        result,
                        futures=_flatten_futures(result.futures, already_open),
                        paper_setup=None,
                        execution_cycle=finalize_execution_cycle(
                            result.execution_cycle, filled=False, detail=already_open
                        ),
                    )
                else:
                    try:
                        evaluation = to_journal_evaluation(result, market)
                        self._scalping_journal.record(
                            evaluation,
                            exchange=self.exchange.id,
                            symbol=self.exchange.symbol,
                            timeframe=SCALPING_TIMEFRAME,
                            settings=scalping_settings(self.settings),
                        )
                        result = replace(
                            result,
                            execution_cycle=finalize_execution_cycle(
                                result.execution_cycle, filled=True, detail=fill_detail
                            ),
                        )
                    except Exception as exc:
                        LOGGER.warning("Scalping journal write failed: %s", exc)
                self._refresh_scalping_report()
            else:
                result = replace(
                    result,
                    execution_cycle=finalize_execution_cycle(
                        result.execution_cycle, filled=True, detail=fill_detail
                    ),
                )

        return result

    def scalping_report(self) -> PaperSetupReport | None:
        return self._scalping_report

    def refresh_active_trader(self) -> ActiveTraderSnapshot | None:
        """Advance the always-on $100 active trader by one 5-minute cycle.

        Independent of the scalping journal: it holds one paper position at a
        time, compounds a single balance, and reports realized PnL growth.
        """
        if self._active_trader is None:
            return None
        candles = self.exchange.fetch_closed_candles(ACTIVE_TRADER_TIMEFRAME)
        market = self.exchange.fetch_market_snapshot()
        shakeout = self.shakeout.analyze(datetime.now(timezone.utc))
        return self._active_trader.tick(candles, market, shakeout=shakeout)

    def mark_active_trader(self, market: MarketSnapshot) -> ActiveTraderSnapshot | None:
        """Refresh active-trader open PnL from the latest market price only."""
        if self._active_trader is None:
            return None
        return self._active_trader.mark_to_market(market)

    def _has_open_scalp(self) -> bool:
        if self._scalping_journal is None:
            return False
        try:
            return (
                self._scalping_journal.count_open(
                    exchange=self.exchange.id,
                    symbol=self.exchange.symbol,
                    timeframe=SCALPING_TIMEFRAME,
                )
                > 0
            )
        except Exception as exc:
            LOGGER.warning("Scalping open-position check failed: %s", exc)
            return False

    def _refresh_scalping_report(self) -> None:
        if self._scalping_journal is None:
            return
        try:
            rows = self._scalping_journal.load_setups()
            self._scalping_report = analyze_setup_rows(
                rows, settings=scalping_settings(self.settings)
            )
        except Exception as exc:
            LOGGER.warning("Scalping report refresh failed: %s", exc)

    def close(self) -> None:
        self.news.close()
        self.scanner.close()
        if self._paper_setup_journal is not None:
            self._paper_setup_journal.close()
        if self._scalping_journal is not None:
            self._scalping_journal.close()
        self.exchange.close()


def _flatten_futures(
    futures: FuturesRecommendation, reason: str
) -> FuturesRecommendation:
    return replace(
        futures,
        action="STAY FLAT",
        side="FLAT",
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        quantity_btc=0.0,
        notional=0.0,
        max_loss=0.0,
        reason=reason,
    )


def next_analysis_boundary(now: datetime, interval_hours: int) -> datetime:
    now = now.astimezone(timezone.utc)
    boundary_hour = ((now.hour // interval_hours) + 1) * interval_hours
    boundary_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return boundary_day + timedelta(hours=boundary_hour)


def _horizon_candles(horizon_hours: int, timeframe: str) -> int:
    timeframe_hours = _timeframe_hours(timeframe)
    if timeframe_hours <= 0:
        return max(1, horizon_hours)
    return max(1, int(math.ceil(horizon_hours / timeframe_hours)))


def _timeframe_hours(timeframe: str) -> float:
    value = timeframe.strip().lower()
    try:
        if value.endswith("m"):
            return float(value[:-1]) / 60.0
        if value.endswith("h"):
            return float(value[:-1])
        if value.endswith("d"):
            return float(value[:-1]) * 24.0
    except ValueError:
        return 4.0
    return 4.0


def _timeframe_label(timeframe: str) -> str:
    if timeframe == "30m":
        return "30min Trade"
    if timeframe == "5m":
        return "5min Trade"
    return f"{timeframe} Trade"


def _probability_candles_for_backtest(
    settings: Settings,
    exchange: str,
    symbol: str,
    live_candles: Any,
    *,
    timeframe: str | None = None,
    horizon_candles: int,
):
    timeframe = timeframe or settings.timeframe
    if settings.history_db_path is None:
        return live_candles
    required = settings.probability_lookback_candles + horizon_candles + 80
    try:
        with HistoryStore(settings.history_db_path) as store:
            stored = store.load_candles(
                exchange,
                symbol,
                timeframe,
                limit=required,
            )
    except Exception as exc:
        LOGGER.warning("Local probability history unavailable: %s", exc)
        return live_candles
    if len(stored) < required:
        return live_candles

    import pandas as pd

    merged = (
        pd.concat([stored, live_candles], ignore_index=True)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
    )
    contiguous = recent_contiguous_candles(merged, timeframe)
    if len(contiguous) < required:
        return live_candles
    return contiguous.tail(required).reset_index(drop=True)


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
    next_futures_refresh = datetime.now(timezone.utc) + timedelta(
        seconds=settings.market_refresh_seconds
    )
    next_news_refresh = datetime.now(timezone.utc) + timedelta(
        seconds=settings.news_refresh_seconds
    )
    next_scalping_refresh = datetime.now(timezone.utc)
    next_active_trader_refresh = datetime.now(timezone.utc)
    next_analysis = evaluation.next_analysis_at
    evaluation = replace(
        evaluation,
        market_health=replace(
            evaluation.market_health,
            next_refresh_at=next_market_refresh,
        ),
        futures_health=replace(
            evaluation.futures_health,
            next_refresh_at=(
                next_futures_refresh
                if service.exchange.id == "binanceusdm"
                else None
            ),
        ),
        news_health=replace(
            evaluation.news_health,
            next_refresh_at=next_news_refresh,
        ),
    )

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
                            service.signal_settings(),
                        )
                        futures, trade_filter, portfolio, meta = (
                            service.build_futures_plan(
                                signal,
                                evaluation.market,
                                probability_forecast=service.probability_forecast,
                                market_context=service.market_context,
                                shakeout=evaluation.shakeout,
                                futures_metrics=evaluation.futures_metrics,
                                technical=technical,
                            )
                        )
                        paper_setup = build_current_paper_setup(
                            futures=futures,
                            technical=technical,
                            evaluated_at=now,
                            settings=settings,
                            market_context=service.market_context,
                            probability_forecast=service.probability_forecast,
                        )
                        evaluation = replace(
                            evaluation,
                            technical=technical,
                            live_technical=None,
                            signal=signal,
                            futures=futures,
                            trade_filter=trade_filter,
                            portfolio=portfolio,
                            signal_profile=service.signal_profile(),
                            meta=meta,
                            paper_setup=paper_setup,
                            price_range=service.price_range,
                            probability_forecast=service.probability_forecast,
                            scenario_forecast=service.scenario_forecast,
                            market_context=service.market_context,
                            evaluated_at=now,
                        )
                        next_analysis = next_analysis_boundary(
                            now, settings.analysis_interval_hours
                        )
                        service.record_signal_evaluation(evaluation)
                        service.record_paper_setup(evaluation)
                        scanner_result = service.refresh_scanner(
                            evaluation.sentiment,
                            evaluation.macro,
                        )
                        evaluation = replace(evaluation, scanner=scanner_result)
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation, f"Analysis refresh failed: {exc}"
                        )
                        next_analysis = now + timedelta(minutes=5)

                if settings.scalping_enabled and now >= next_scalping_refresh:
                    try:
                        scalping = service.refresh_scalping()
                        evaluation = replace(evaluation, scalping=scalping)
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation, f"Scalping refresh failed: {exc}"
                        )
                    next_scalping_refresh = now + timedelta(
                        seconds=settings.scalping_refresh_seconds
                    )

                if settings.active_trader_enabled and now >= next_active_trader_refresh:
                    try:
                        active_trader = service.refresh_active_trader()
                        evaluation = replace(evaluation, active_trader=active_trader)
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation, f"Active trader refresh failed: {exc}"
                        )
                    next_active_trader_refresh = now + timedelta(
                        seconds=settings.active_trader_refresh_seconds
                    )

                if news_future is None and now >= next_news_refresh:
                    news_future = news_executor.submit(service.refresh_news)
                    next_news_refresh = now + timedelta(
                        seconds=settings.news_refresh_seconds
                    )
                    evaluation = replace(
                        evaluation,
                        news_health=replace(
                            evaluation.news_health,
                            status="REFRESHING",
                            last_attempt_at=now,
                            next_refresh_at=next_news_refresh,
                            detail=None,
                        ),
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
                            service=service,
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
                                active_trader=service.mark_active_trader(market)
                                or evaluation.active_trader,
                                stream_status="REST fallback",
                                market_health=RefreshHealth(
                                    status="REST",
                                    last_success_at=market.timestamp,
                                    last_attempt_at=now,
                                    next_refresh_at=next_market_refresh,
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

                    next_market_refresh = now + timedelta(
                        seconds=settings.market_refresh_seconds
                    )

                if (
                    service.exchange.id == "binanceusdm"
                    and now >= next_futures_refresh
                ):
                    try:
                        metrics, errors = service.refresh_futures_metrics()
                        for error in errors:
                            evaluation = _with_error(evaluation, error)
                        shakeout = service.apply_futures_metrics(metrics, now)
                        evaluation = replace(
                            evaluation,
                            futures_metrics=(
                                metrics
                                if metrics is not None
                                else evaluation.futures_metrics
                            ),
                            shakeout=shakeout,
                            futures_health=_completed_health(
                                evaluation.futures_health,
                                succeeded=metrics is not None,
                                errors=errors,
                                attempted_at=now,
                            ),
                        )
                        evaluation = _apply_sentiment_context(
                            evaluation, settings, service=service
                        )
                        evaluation = _apply_current_trade_filters(evaluation, service)
                    except Exception as exc:
                        evaluation = _with_error(
                            evaluation,
                            f"Futures metrics refresh failed: {exc}",
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
                    next_futures_refresh = now + timedelta(
                        seconds=settings.market_refresh_seconds
                    )

                evaluation = replace(
                    evaluation,
                    next_analysis_at=next_analysis,
                    market_health=replace(
                        evaluation.market_health,
                        next_refresh_at=next_market_refresh,
                    ),
                    futures_health=replace(
                        evaluation.futures_health,
                        next_refresh_at=(
                            next_futures_refresh
                            if service.exchange.id == "binanceusdm"
                            else None
                        ),
                    ),
                    news_health=replace(
                        evaluation.news_health,
                        next_refresh_at=next_news_refresh,
                    ),
                )
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
                    active_trader=service.mark_active_trader(market)
                    or current.active_trader,
                    stream_status="LIVE",
                    stream_updated_at=event.received_at,
                    market_health=replace(
                        current.market_health,
                        status="LIVE",
                        last_success_at=event.received_at,
                        detail=None,
                    ),
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
                    market_context=service.market_context,
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
                current = replace(
                    current,
                    stream_status="LIVE",
                    market_health=replace(
                        current.market_health,
                        status="LIVE",
                        last_success_at=event.received_at,
                        detail=None,
                    ),
                )
            else:
                current = _with_error(current, event.message)
                current = replace(
                    current,
                    stream_status="RECONNECTING",
                    market_health=replace(
                        current.market_health,
                        status="RECONNECTING",
                        last_attempt_at=event.received_at,
                        detail=event.message,
                    ),
                )
        elif event.kind in {"depth", "trade", "liquidation"}:
            try:
                current = replace(
                    current,
                    shakeout=service.apply_microstructure(
                        event.kind, event.payload, event.received_at
                    ),
                    stream_updated_at=event.received_at,
                )
                current = _apply_current_trade_filters(current, service)
            except Exception as exc:
                current = _with_error(
                    current, f"Microstructure update failed: {exc}"
                )
    return current


def _apply_current_trade_filters(
    evaluation: Evaluation,
    service: BotService,
) -> Evaluation:
    futures, trade_filter, portfolio, meta = service.build_futures_plan(
        evaluation.signal,
        evaluation.market,
        probability_forecast=evaluation.probability_forecast,
        market_context=evaluation.market_context,
        shakeout=evaluation.shakeout,
        futures_metrics=evaluation.futures_metrics,
        technical=evaluation.technical,
    )
    paper_setup = build_current_paper_setup(
        futures=futures,
        technical=evaluation.technical,
        evaluated_at=evaluation.evaluated_at,
        settings=service.settings,
        market_context=evaluation.market_context,
        probability_forecast=evaluation.probability_forecast,
    )
    return replace(
        evaluation,
        futures=futures,
        trade_filter=trade_filter,
        portfolio=portfolio,
        meta=meta,
        paper_setup=paper_setup,
    )


def _apply_sentiment_context(
    evaluation: Evaluation,
    settings: Settings,
    service: BotService | None = None,
) -> Evaluation:
    sentiment = blend_derivatives_crowding(
        evaluation.sentiment,
        evaluation.futures_metrics,
    )
    if sentiment == evaluation.sentiment:
        return evaluation
    signal_settings = service.signal_settings() if service is not None else settings
    signal = calculate_signal(
        evaluation.technical, sentiment, evaluation.macro, signal_settings
    )
    return replace(evaluation, sentiment=sentiment, signal=signal)


def _apply_news_refresh(
    evaluation: Evaluation,
    sentiment: SentimentAnalysis | None,
    macro: MacroAnalysis | None,
    errors: tuple[str, ...],
    settings: Settings,
    updated_at: datetime,
    service: BotService | None = None,
) -> Evaluation:
    current = evaluation
    for error in errors:
        current = _with_error(current, error)
    if sentiment is None or macro is None:
        return replace(
            current,
            news_health=_completed_health(
                current.news_health,
                succeeded=False,
                errors=errors,
                attempted_at=updated_at,
            ),
        )

    sentiment = blend_derivatives_crowding(sentiment, current.futures_metrics)
    signal_settings = service.signal_settings() if service is not None else settings
    signal = calculate_signal(current.technical, sentiment, macro, signal_settings)
    portfolio = current.portfolio
    meta = current.meta
    if service is not None:
        futures, trade_filter, portfolio, meta = service.build_futures_plan(
            signal,
            current.market,
            probability_forecast=current.probability_forecast,
            market_context=current.market_context,
            shakeout=current.shakeout,
            futures_metrics=current.futures_metrics,
            technical=current.technical,
        )
    else:
        futures, trade_filter = apply_do_not_trade_filters(
            build_futures_recommendation(signal, current.market, settings),
            settings,
            probability_forecast=current.probability_forecast,
            market_context=current.market_context,
            shakeout=current.shakeout,
            futures_metrics=current.futures_metrics,
        )
    paper_setup = build_current_paper_setup(
        futures=futures,
        technical=current.technical,
        evaluated_at=updated_at,
        settings=settings,
        market_context=current.market_context,
        probability_forecast=current.probability_forecast,
    )
    return replace(
        current,
        sentiment=sentiment,
        macro=macro,
        signal=signal,
        futures=futures,
        trade_filter=trade_filter,
        portfolio=portfolio,
        meta=meta,
        paper_setup=paper_setup,
        evaluated_at=updated_at,
        news_updated_at=updated_at,
        news_health=_completed_health(
            current.news_health,
            succeeded=True,
            errors=errors,
            attempted_at=updated_at,
        ),
    )


def _initial_futures_health(
    exchange_id: str,
    metrics: FuturesMetrics | None,
    errors: tuple[str, ...],
    attempted_at: datetime,
) -> RefreshHealth:
    if exchange_id != "binanceusdm":
        return RefreshHealth(status="N/A")
    return _completed_health(
        RefreshHealth(),
        succeeded=metrics is not None,
        errors=errors,
        attempted_at=attempted_at,
    )


def _completed_health(
    previous: RefreshHealth,
    *,
    succeeded: bool,
    errors: tuple[str, ...],
    attempted_at: datetime,
) -> RefreshHealth:
    status = "OK" if succeeded and not errors else "DEGRADED" if succeeded else "FAILED"
    return replace(
        previous,
        status=status,
        last_success_at=attempted_at if succeeded else previous.last_success_at,
        last_attempt_at=attempted_at,
        detail="; ".join(errors[:2]) if errors else None,
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
    _configure_console_encoding()
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    if args.exchange:
        settings = replace(settings, exchange=args.exchange)
    raise SystemExit(run(settings, once=args.once))


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    main()
