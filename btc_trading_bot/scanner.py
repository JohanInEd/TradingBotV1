from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import ExchangeClient
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.indicators import analyze_multi_timeframe
from btc_trading_bot.market_context import analyze_market_context
from btc_trading_bot.models import (
    Evaluation,
    MacroAnalysis,
    MarketScannerResult,
    PortfolioState,
    ScannerCandidate,
    SentimentAnalysis,
)
from btc_trading_bot.news import base_asset, sentiment_for_asset
from btc_trading_bot.paper_setups import PaperSetupJournal
from btc_trading_bot.portfolio import (
    check_portfolio_entry,
    register_open_position,
)
from btc_trading_bot.strategy import calculate_signal

LOGGER = logging.getLogger(__name__)
SCANNER_MAX_WORKERS = 4


@dataclass(frozen=True, slots=True)
class _SymbolScan:
    candidate: ScannerCandidate
    evaluation: Evaluation | None = None
    exchange_id: str | None = None
    resolved_symbol: str | None = None


class MarketScanner:
    def __init__(
        self,
        settings: Settings,
        journal: PaperSetupJournal | None = None,
    ) -> None:
        self.settings = settings
        self.journal = journal
        self._clients: dict[str, ExchangeClient] = {}
        self._clients_lock = threading.Lock()

    def scan(
        self,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
        *,
        portfolio_state: PortfolioState | None = None,
        primary_symbol: str | None = None,
    ) -> MarketScannerResult | None:
        symbols = self.settings.scanner_symbols
        if not symbols:
            return None

        scans: list[_SymbolScan] = []
        errors: list[str] = []
        worker_count = min(SCANNER_MAX_WORKERS, len(symbols))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="scanner",
        ) as executor:
            futures = {
                symbol: executor.submit(
                    self._scan_symbol_guarded, symbol, sentiment, macro
                )
                for symbol in symbols
            }
        for symbol in symbols:
            scan, error = futures[symbol].result()
            scans.append(scan)
            if error is not None:
                errors.append(error)

        ranked = sorted(scans, key=lambda scan: _rank_key(scan.candidate))
        candidates = self._apply_portfolio_allocation(
            ranked,
            portfolio_state,
            primary_symbol=primary_symbol,
        )
        return MarketScannerResult(
            symbols=symbols,
            candidates=tuple(candidates),
            generated_at=datetime.now(timezone.utc),
            errors=tuple(errors),
            portfolio=portfolio_state,
        )

    def close(self) -> None:
        with self._clients_lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive close
                LOGGER.debug("Scanner client close failed", exc_info=True)

    def _apply_portfolio_allocation(
        self,
        ranked: list[_SymbolScan],
        portfolio_state: PortfolioState | None,
        *,
        primary_symbol: str | None,
    ) -> list[ScannerCandidate]:
        if portfolio_state is None:
            return [scan.candidate for scan in ranked]

        state = portfolio_state
        candidates: list[ScannerCandidate] = []
        for scan in ranked:
            candidate = scan.candidate
            if candidate.action not in {"GO LONG", "GO SHORT"}:
                candidates.append(candidate)
                continue
            if (
                primary_symbol is not None
                and scan.resolved_symbol == primary_symbol
            ):
                # The main evaluation flow owns recording for the primary
                # symbol; avoid double-counting it here.
                candidates.append(
                    replace(candidate, portfolio_status="PRIMARY")
                )
                continue

            evaluation = scan.evaluation
            side = "LONG" if candidate.action == "GO LONG" else "SHORT"
            max_loss = (
                evaluation.futures.max_loss
                if evaluation is not None and evaluation.futures is not None
                else 0.0
            )
            candle_time = (
                evaluation.technical.candle_time
                if evaluation is not None
                else None
            )
            decision = check_portfolio_entry(
                state,
                symbol=scan.resolved_symbol or candidate.symbol,
                side=side,
                max_loss=max_loss,
                settings=self.settings,
                candle_time=candle_time,
            )
            if decision.status == "TRACKED":
                candidates.append(
                    replace(candidate, portfolio_status="TRACKED")
                )
                continue
            if not decision.allowed:
                candidates.append(
                    replace(
                        candidate,
                        portfolio_status=f"BLOCKED: {decision.reasons[0]}",
                    )
                )
                continue

            state = register_open_position(
                state,
                symbol=scan.resolved_symbol or candidate.symbol,
                side=side,
                max_loss=max_loss,
            )
            recorded = self._record_setup(scan)
            candidates.append(
                replace(
                    candidate,
                    portfolio_status="RECORDED" if recorded else "ALLOWED",
                )
            )
        return candidates

    def _record_setup(self, scan: _SymbolScan) -> bool:
        if (
            self.journal is None
            or scan.evaluation is None
            or scan.exchange_id is None
            or scan.resolved_symbol is None
        ):
            return False
        try:
            return self.journal.record(
                scan.evaluation,
                exchange=scan.exchange_id,
                symbol=scan.resolved_symbol,
                timeframe=self.settings.timeframe,
                settings=self.settings,
            )
        except Exception as exc:
            LOGGER.warning(
                "Scanner paper setup record failed for %s: %s",
                scan.resolved_symbol,
                exc,
            )
            return False

    def _scan_symbol_guarded(
        self,
        symbol: str,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
    ) -> tuple[_SymbolScan, str | None]:
        try:
            return self._scan_symbol(symbol, sentiment, macro), None
        except Exception as exc:
            self._drop_client(symbol)
            return (
                _SymbolScan(
                    candidate=ScannerCandidate(
                        symbol=symbol,
                        action="UNAVAILABLE",
                        side="ERROR",
                        confidence=0.0,
                        price=None,
                        change_24h=None,
                        signal="UNAVAILABLE",
                        score=0.0,
                        raw_score=0.0,
                        technical_score=0.0,
                        sentiment_score=sentiment.score,
                        macro_score=macro.score,
                        market_regime=None,
                        volatility_regime=None,
                        reason=str(exc),
                        error=str(exc),
                    )
                ),
                f"{symbol}: {exc}",
            )

    def _scan_symbol(
        self,
        symbol: str,
        sentiment: SentimentAnalysis,
        macro: MacroAnalysis,
    ) -> _SymbolScan:
        client = self._client_for(symbol)
        settings = replace(self.settings, symbol=symbol)
        symbol_sentiment, asset_applied = sentiment_for_asset(
            sentiment, base_asset(symbol)
        )
        market = client.fetch_market_snapshot()
        primary = client.fetch_closed_candles(settings.timeframe)
        daily = client.fetch_closed_candles(settings.daily_timeframe)
        hourly = client.fetch_closed_candles(settings.entry_timeframe)
        self._resolve_journal_setups(client, primary)
        technical = analyze_multi_timeframe(
            primary,
            daily,
            hourly,
            primary_weight=settings.primary_timeframe_weight,
            daily_weight=settings.daily_timeframe_weight,
            hourly_weight=settings.entry_timeframe_weight,
        )
        signal = calculate_signal(technical, symbol_sentiment, macro, settings)
        futures = build_futures_recommendation(signal, market, settings)
        context = analyze_market_context(primary)
        evaluated_at = datetime.now(timezone.utc)
        candidate = ScannerCandidate(
            symbol=client.symbol,
            action=futures.action,
            side=futures.side,
            confidence=futures.confidence,
            price=market.price,
            change_24h=market.change_24h,
            signal=signal.signal,
            score=signal.score,
            raw_score=signal.raw_score,
            technical_score=technical.score,
            sentiment_score=symbol_sentiment.score,
            macro_score=macro.score,
            market_regime=context.structure_regime,
            volatility_regime=context.volatility_regime,
            reason=_candidate_reason(
                futures.action,
                technical.score,
                symbol_sentiment,
                macro,
                asset_applied=asset_applied,
                asset=base_asset(symbol),
            ),
            sentiment_basis="asset" if asset_applied else "global",
        )
        evaluation = None
        if futures.side in {"LONG", "SHORT"}:
            evaluation = Evaluation(
                market=market,
                technical=technical,
                sentiment=symbol_sentiment,
                macro=macro,
                signal=signal,
                futures=futures,
                market_context=context,
                evaluated_at=evaluated_at,
                next_analysis_at=evaluated_at,
            )
        return _SymbolScan(
            candidate=candidate,
            evaluation=evaluation,
            exchange_id=client.id,
            resolved_symbol=client.symbol,
        )

    def _resolve_journal_setups(self, client: ExchangeClient, candles: Any) -> None:
        if self.journal is None:
            return
        try:
            self.journal.resolve_with_candles(
                candles,
                exchange=client.id,
                symbol=client.symbol,
                timeframe=self.settings.timeframe,
            )
        except Exception as exc:
            LOGGER.warning(
                "Scanner outcome resolution failed for %s: %s",
                client.symbol,
                exc,
            )

    def _client_for(self, symbol: str) -> ExchangeClient:
        with self._clients_lock:
            client = self._clients.get(symbol)
            if client is not None:
                return client
        client = ExchangeClient(replace(self.settings, symbol=symbol))
        with self._clients_lock:
            existing = self._clients.get(symbol)
            if existing is not None:
                client.close()
                return existing
            self._clients[symbol] = client
        return client

    def _drop_client(self, symbol: str) -> None:
        with self._clients_lock:
            client = self._clients.pop(symbol, None)
        if client is not None:
            try:
                client.close()
            except Exception:  # pragma: no cover - defensive close
                LOGGER.debug("Scanner client close failed", exc_info=True)


def _candidate_reason(
    action: str,
    technical_score: float,
    sentiment: SentimentAnalysis,
    macro: MacroAnalysis,
    *,
    asset_applied: bool = False,
    asset: str = "",
) -> str:
    if action == "GO LONG":
        direction = "bullish closed-candle confirmation"
    elif action == "GO SHORT":
        direction = "bearish closed-candle confirmation"
    else:
        direction = "no full multi-timeframe confirmation"
    sentiment_note = (
        f"{asset} headline sentiment {sentiment.score:+.3f}"
        if asset_applied
        else f"sentiment {sentiment.score:+.3f} ({sentiment.label})"
    )
    return (
        f"{direction}; technical {technical_score:+.3f}, "
        f"{sentiment_note}, "
        f"macro {macro.status.lower()}"
    )


def _rank_key(candidate: ScannerCandidate) -> tuple[int, float]:
    if candidate.action in {"GO LONG", "GO SHORT"}:
        group = 0
    elif candidate.action == "STAY FLAT":
        group = 1
    else:
        group = 2
    return (group, -candidate.confidence)
