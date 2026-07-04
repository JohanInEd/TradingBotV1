from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from btc_trading_bot.binance_demo import BinanceDemoClient, BinanceDemoError, BinanceDemoOrder
from btc_trading_bot.config import Settings
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.models import (
    ActiveTraderCyclePoint,
    ActiveTradeFill,
    ActiveTraderAccount,
    ActiveTraderSnapshot,
    ActiveTradePosition,
    ExecutionCycle,
    ExecutionStage,
    MarketSnapshot,
    ShakeoutAnalysis,
    TradeFilterResult,
)
from btc_trading_bot.paper_setups import (
    OUTCOME_EXPIRED,
    OUTCOME_OPEN,
    OUTCOME_SL,
    OUTCOME_TP,
    PaperSetupResolution,
    _iso,
    build_current_paper_setup,
    _normalise_candles,
    resolve_setup_outcome,
)
from btc_trading_bot.scalping import (
    SCALPING_TIMEFRAME,
    build_execution_cycle,
    evaluate_scalping,
    finalize_execution_cycle,
    scalping_settings,
)

ACTIVE_TRADER_TIMEFRAME = SCALPING_TIMEFRAME  # closed 5-minute candles
DIRECTIONAL_SIDES = frozenset({"LONG", "SHORT"})
GROWTH_CURVE_LIMIT = 240
RECENT_FILLS_LIMIT = 12
ACTIVE_TRADER_POSITION_SECONDS = 300
ACTIVE_TRADER_CYCLE_HISTORY_LIMIT = 120
COOLDOWN_EXIT_REASONS = frozenset({"EXPIRED", "STOP_LOSS", "PROTECTED_STOP"})


class ActiveTrader:
    """Always-on BTC paper execution engine seeded with a small fixed
    account (default $100).

    Every tick runs the same execution cycle as the scalping engine — scam
    detect, validate, size, fill, settle — but instead of only journaling
    signals it actively holds one paper position at a time and compounds a
    single balance, so the dashboard can show realized PnL growth over the
    session. Position sizing uses the *current* equity, so wins and losses
    compound.

    Paper mode never requests exchange credentials or submits orders. In
    binance_demo mode it mirrors the same lifecycle with market orders against
    Binance USD-M Demo Trading only.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        demo_client: BinanceDemoClient | None = None,
    ) -> None:
        self.settings = settings
        self.execution_mode = settings.active_trader_execution
        self._demo_error = ""
        self._demo_client = demo_client
        if self.execution_mode == "binance_demo" and self._demo_client is None:
            try:
                self._demo_client = BinanceDemoClient(settings)
            except BinanceDemoError as exc:
                self._demo_error = str(exc)
        self.starting_equity = max(1.0, float(settings.active_trader_equity))
        self._equity = self.starting_equity
        self._peak_equity = self.starting_equity
        self._max_drawdown_percent = 0.0
        self._position: ActiveTradePosition | None = None
        self._fills: list[ActiveTradeFill] = []
        self._wins = 0
        self._losses = 0
        self._last_action = "IDLE"
        self._last_detail = "Waiting for the first closed 5-minute candle."
        self._evaluated_at = datetime.now(timezone.utc)
        self._journal_path = settings.active_trader_journal_path
        self._last_cycle: ExecutionCycle | None = None
        self._last_technical: Any = None
        self._last_signal: Any = None
        self._last_futures: Any = None
        self._cycle_history: list[ActiveTraderCyclePoint] = []
        self._side_cooldown_until: dict[str, datetime] = {}
        self._growth: list[dict[str, Any]] = [
            {
                "time": None,
                "equity": self.starting_equity,
                "net_pnl": 0.0,
                "net_r": 0.0,
                "return_percent": 0.0,
                "outcome": "START",
                "side": None,
            }
        ]

    def tick(
        self,
        candles: Any,
        market: MarketSnapshot,
        *,
        shakeout: ShakeoutAnalysis | None = None,
    ) -> ActiveTraderSnapshot:
        """Advance the account by one execution cycle.

        Order of operations: settle any open position from newer closed
        candles, then run the execution cycle on the just-closed candle and
        fill a fresh position when the cycle clears and the account is flat.
        When a position is already open, the cycle still prepares the current
        long/short candidate so the dashboard is ready to fill as soon as the
        running position settles.
        """
        now = datetime.now(timezone.utc)
        self._evaluated_at = now

        settlement = self._settle_open_position(_normalise_candles(candles))
        settle_detail = settlement[1] if settlement is not None else None
        settled_fill = settlement[0] if settlement is not None else None

        try:
            active_settings = replace(
                self.settings,
                # Size off the live (compounding) balance so wins and losses
                # roll forward into the next position.
                paper_account_equity=max(1.0, self._equity),
                scalping_risk_per_trade=self.settings.active_trader_risk_per_trade,
            )
            result = evaluate_scalping(
                candles, market, active_settings, shakeout=shakeout
            )
        except Exception:
            # Indicators need enough candle history; stay idle until ready.
            if settle_detail is not None:
                self._last_action = "SETTLE"
                self._last_detail = settle_detail
            return self._snapshot(
                cycle=None, technical=None, signal=None, futures=None, market=market
            )

        mode_settings = scalping_settings(active_settings)
        signal = _force_active_signal(result.signal, result.technical)
        futures = build_futures_recommendation(signal, market, mode_settings)
        futures = replace(
            futures,
            reason=(
                f"Active trader forced a 5-minute {futures.side} cycle from "
                f"technical bias {result.technical.score:+.2f}; no flat candle."
            ),
        )
        trade_filter = TradeFilterResult(
            status="PASS",
            allowed=True,
            original_action=futures.action,
            reasons=("BTC 5-minute candle validated for active trader execution.",),
        )
        setup = build_current_paper_setup(
            futures=futures,
            technical=result.technical,
            evaluated_at=result.evaluated_at,
            settings=mode_settings,
            market_context=result.market_context,
            probability_forecast=None,
        )
        cycle = build_execution_cycle(
            trade_filter=trade_filter,
            futures=futures,
            shakeout=shakeout,
            paper_setup=setup,
        )
        if futures.side in DIRECTIONAL_SIDES and setup is not None:
            # Re-size the fill to a fixed fraction of the current balance so a
            # small $100 account visibly compounds, and rebuild the cycle so its
            # "Size" stage matches the position we actually take.
            futures, setup = self._risk_size(futures, setup)
            cycle = build_execution_cycle(
                trade_filter=trade_filter,
                futures=futures,
                shakeout=shakeout,
                paper_setup=setup,
            )
            cycle = self._handle_directional(
                setup,
                now,
                cycle,
                settled_fill=settled_fill,
                technical=result.technical,
            )
        elif settle_detail is not None:
            self._last_action = "SETTLE"
            self._last_detail = settle_detail
        else:
            self._last_action = cycle.status if cycle is not None else "IDLE"
            self._last_detail = _cycle_headline(cycle)

        return self._snapshot(
            cycle=cycle,
            technical=result.technical,
            signal=signal,
            futures=futures,
            market=market,
        )

    def mark_to_market(self, market: MarketSnapshot) -> ActiveTraderSnapshot:
        """Refresh the open-position PnL view from the latest public price.

        This does not open new trades. It can close an open paper position
        early when the live mark is net-profitable, so the 1-second loop can
        prepare the next fill before the current 5-minute candle closes.
        """
        self._evaluated_at = datetime.now(timezone.utc)
        self._settle_profitable_mark(market)
        return self._snapshot(
            cycle=None,
            technical=None,
            signal=None,
            futures=None,
            market=market,
        )

    def _risk_size(self, futures: Any, setup: Any) -> tuple[Any, Any]:
        """Size the active fill like a small futures scalp.

        The active trader uses fixed isolated paper margin (default $50) with
        the configured futures leverage (default 5x), instead of the main
        system's risk-budget sizing. Max loss is still estimated from the stop
        distance so the dashboard can show the downside of that paper fill.
        """
        if setup.entry_price <= 0:
            return futures, setup
        leverage = max(1, int(self.settings.futures_leverage or 1))
        margin = min(max(1.0, self._equity), self.settings.active_trader_margin_usd)
        notional = margin * leverage
        quantity = notional / setup.entry_price
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        max_loss = quantity * stop_distance
        sized_futures = replace(
            futures,
            quantity_btc=quantity,
            notional=notional,
            max_loss=max_loss,
            leverage=leverage,
        )
        sized_setup = replace(
            setup,
            quantity_btc=quantity,
            notional=notional,
            max_loss=max_loss,
            leverage=leverage,
            position_estimate=(
                f"{quantity:.6f} BTC / ${notional:,.2f} notional "
                f"(${margin:,.2f} margin at {leverage}x)"
            ),
        )
        return sized_futures, sized_setup

    def _handle_directional(
        self,
        setup: Any,
        now: datetime,
        cycle: ExecutionCycle | None,
        *,
        settled_fill: ActiveTradeFill | None = None,
        technical: Any = None,
    ) -> ExecutionCycle | None:
        if self._position is not None:
            detail = (
                f"Prepared {setup.side} candidate at ${setup.entry_price:,.2f} "
                f"while current {self._position.side} position is running; "
                "waiting for TP, SL, or expiry before fill."
            )
            self._last_action = f"PREPARED {setup.side}"
            self._last_detail = detail
            return finalize_execution_cycle(cycle, filled=False, detail=detail)

        allowed, reentry_detail = self._reentry_decision(setup, settled_fill, technical)
        if not allowed:
            self._last_action = "REENTRY WAIT"
            self._last_detail = reentry_detail
            return finalize_execution_cycle(cycle, filled=False, detail=reentry_detail)

        cooldown_allowed, cooldown_detail = self._cooldown_decision(setup)
        if not cooldown_allowed:
            self._last_action = "COOLDOWN"
            self._last_detail = cooldown_detail
            return _cooldown_cycle(cycle, cooldown_detail)

        if cycle is None or cycle.status != "PENDING":
            # Scam detect or validate blocked this setup before the fill stage,
            # so the cycle never reaches "fill". Respect the gate and stay flat.
            self._last_action = "BLOCKED"
            self._last_detail = _cycle_headline(cycle)
            return cycle

        position = self._open_position(setup, now)
        if position is None:
            detail = "Cleared setup could not be sized into a paper position."
            self._last_action = "SKIP"
            self._last_detail = detail
            return finalize_execution_cycle(cycle, filled=False, detail=detail)

        position, demo_error = self._prepare_demo_open(position)
        if demo_error is not None:
            detail = f"Binance Demo fill skipped: {demo_error}"
            self._last_action = "DEMO NOT READY"
            self._last_detail = detail
            return finalize_execution_cycle(cycle, filled=False, detail=detail)

        self._position = position
        self._record_open_event(position, setup)
        detail = self._open_detail(position)
        self._last_action = f"FILL {position.side}"
        self._last_detail = detail
        return finalize_execution_cycle(cycle, filled=True, detail=detail)

    def _open_position(
        self, setup: Any, now: datetime
    ) -> ActiveTradePosition | None:
        if setup is None or setup.quantity_btc <= 0:
            return None
        expires_at = setup.candle_time + timedelta(
            seconds=ACTIVE_TRADER_POSITION_SECONDS
        )
        return ActiveTradePosition(
            side=setup.side,
            entry_price=setup.entry_price,
            stop_loss=setup.stop_loss,
            take_profit=setup.take_profit,
            quantity_btc=setup.quantity_btc,
            notional=setup.notional,
            max_loss=setup.max_loss,
            reward_to_risk=setup.reward_to_risk,
            opened_at=now,
            candle_time=setup.candle_time,
            expires_at=expires_at,
            original_stop_loss=setup.stop_loss,
            protected_stop_loss=setup.stop_loss,
            execution_mode=self.execution_mode,
        )

    def _settle_open_position(
        self, candle_dicts: list[dict[str, Any]]
    ) -> tuple[ActiveTradeFill, str] | None:
        position = self._position
        if position is None or not candle_dicts:
            return None
        setup_dict = {
            "outcome": OUTCOME_OPEN,
            # The active trader fills immediately, so the position is already
            # "entered"; only look for the exit on newer candles.
            "entry_reached": 1,
            "entry_reached_at": _iso(position.opened_at),
            "closed_candle_at": _iso(position.candle_time),
            "side": position.side,
            "entry": position.entry_price,
            "stop_loss": position.protected_stop_loss or position.stop_loss,
            "take_profit": position.take_profit,
            "expires_at": _iso(position.expires_at),
        }
        for candle in candle_dicts:
            setup_dict["stop_loss"] = position.protected_stop_loss or position.stop_loss
            resolution = resolve_setup_outcome(
                setup_dict,
                candle,
                horizon_hours=self.settings.scalping_horizon_hours,
            )
            resolution = self._promote_positive_expiry_to_take_profit(
                position, resolution, candle
            )
            if resolution.outcome != OUTCOME_OPEN:
                close_order, close_error = self._prepare_demo_close(position)
                if close_error is not None:
                    self._last_action = "DEMO CLOSE FAILED"
                    self._last_detail = f"Binance Demo close failed: {close_error}"
                    return None
                fill = self._record_settlement(
                    position,
                    resolution,
                    close_order=close_order,
                )
                self._position = None
                return fill, (
                    f"Settled {position.side} {resolution.outcome} for "
                    f"${fill.net_pnl:,.2f} via {fill.exit_reason} "
                    f"(equity ${self._equity:,.2f})."
                )
            position = self._protect_open_position(position, candle)
            self._position = position
        return None

    def _settle_profitable_mark(
        self, market: MarketSnapshot
    ) -> tuple[ActiveTradeFill, str] | None:
        position = self._position
        if position is None or market.price is None:
            return None
        mode = self.settings.active_trader_early_take_profit_mode
        if mode == "disabled":
            return None

        exit_price = float(market.price)
        r_multiple = self._r_multiple_at_price(position, exit_price)
        if r_multiple <= 0:
            return None
        net_pnl = self._estimate_net_pnl(
            position,
            exit_price=exit_price,
            r_multiple=r_multiple,
        )
        if net_pnl <= 0:
            return None
        roi_percent = self._roi_percent(position, net_pnl=net_pnl)
        if roi_percent < self.settings.active_trader_early_take_profit_min_roi_percent:
            return None
        if (
            mode == "progress"
            and self._favorable_progress_percent(position, exit_price)
            < self.settings.active_trader_force_profit_progress_percent
        ):
            return None

        closed_at = market.timestamp or self._evaluated_at
        resolution = PaperSetupResolution(
            changed=True,
            outcome=OUTCOME_TP,
            entry_reached=True,
            entry_reached_at=position.opened_at,
            outcome_at=closed_at,
            outcome_candle_at=closed_at,
            outcome_price=exit_price,
            r_multiple=r_multiple,
            duration_hours=(
                max(0.0, (closed_at - position.opened_at).total_seconds() / 3600.0)
                if closed_at is not None
                else None
            ),
        )
        close_order, close_error = self._prepare_demo_close(position)
        if close_error is not None:
            self._last_action = "DEMO CLOSE FAILED"
            self._last_detail = f"Binance Demo close failed: {close_error}"
            return None
        fill = self._record_settlement(position, resolution, close_order=close_order)
        self._position = None
        detail = (
            f"Live mark closed {position.side} for ${fill.net_pnl:,.2f} "
            f"via {fill.exit_reason} before the 5-minute candle closed "
            f"(equity ${self._equity:,.2f})."
        )
        self._last_action = "LIVE TP"
        self._last_detail = detail
        self._last_cycle = _settle_cycle(self._last_cycle, detail)
        return fill, detail

    def _promote_positive_expiry_to_take_profit(
        self,
        position: ActiveTradePosition,
        resolution: PaperSetupResolution,
        candle: dict[str, Any],
    ) -> PaperSetupResolution:
        """Let the 5m active trader bank a configured profitable close early."""
        if (
            resolution.outcome != OUTCOME_EXPIRED
            or resolution.outcome_price is None
            or resolution.r_multiple is None
            or resolution.r_multiple <= 0
        ):
            return resolution
        mode = self.settings.active_trader_early_take_profit_mode
        if mode == "disabled":
            return resolution
        net_pnl = self._estimate_net_pnl(
            position,
            exit_price=resolution.outcome_price,
            r_multiple=resolution.r_multiple,
        )
        if net_pnl <= 0:
            return resolution
        roi_percent = self._roi_percent(position, net_pnl=net_pnl)
        if roi_percent < self.settings.active_trader_early_take_profit_min_roi_percent:
            return resolution
        if mode == "progress":
            progress = max(
                self._favorable_progress_percent(position, resolution.outcome_price),
                self._favorable_progress_percent(
                    position, _favorable_candle_price(position, candle)
                ),
            )
            if progress < self.settings.active_trader_force_profit_progress_percent:
                return resolution
        return PaperSetupResolution(
            changed=resolution.changed,
            outcome=OUTCOME_TP,
            entry_reached=resolution.entry_reached,
            entry_reached_at=resolution.entry_reached_at,
            outcome_at=resolution.outcome_at,
            outcome_candle_at=resolution.outcome_candle_at,
            outcome_price=resolution.outcome_price,
            r_multiple=resolution.r_multiple,
            duration_hours=resolution.duration_hours,
        )

    def _protect_open_position(
        self,
        position: ActiveTradePosition,
        candle: dict[str, Any],
    ) -> ActiveTradePosition:
        progress = self._favorable_progress_percent(
            position, _favorable_candle_price(position, candle)
        )
        if progress < self.settings.active_trader_breakeven_progress_percent:
            return position

        if position.side == "LONG":
            protected_stop = max(
                position.protected_stop_loss or position.stop_loss,
                position.entry_price,
            )
        else:
            protected_stop = min(
                position.protected_stop_loss or position.stop_loss,
                position.entry_price,
            )
        if protected_stop == position.protected_stop_loss:
            return position
        return replace(position, protected_stop_loss=protected_stop)

    def _reentry_decision(
        self,
        setup: Any,
        settled_fill: ActiveTradeFill | None,
        technical: Any,
    ) -> tuple[bool, str]:
        if settled_fill is None:
            return True, ""
        mode = self.settings.active_trader_reentry_mode
        if mode == "immediate":
            return True, ""
        if mode == "disabled_after_exit":
            return (
                False,
                "Same-cycle re-entry disabled after settling the previous paper position.",
            )
        if mode == "same_direction" and setup.side != settled_fill.side:
            return (
                False,
                f"Re-entry requires {settled_fill.side}; new cycle is {setup.side}.",
            )
        if mode == "flip_on_reversal" and setup.side != settled_fill.side:
            score = abs(_active_directional_score(technical))
            threshold = self.settings.active_trader_flip_threshold
            if score < threshold:
                return (
                    False,
                    f"Flip from {settled_fill.side} to {setup.side} needs "
                    f"5m bias >= {threshold:.2f}; current is {score:.2f}.",
                )
        return True, ""

    def _record_settlement(
        self,
        position: ActiveTradePosition,
        resolution: Any,
        *,
        close_order: BinanceDemoOrder | None = None,
    ) -> ActiveTradeFill:
        exit_price = resolution.outcome_price or position.entry_price
        r_multiple = resolution.r_multiple if resolution.r_multiple is not None else 0.0
        gross_pnl = r_multiple * position.max_loss
        exit_notional = position.quantity_btc * exit_price
        turnover = position.notional + abs(exit_notional)
        fees = turnover * self.settings.paper_ledger_fee_rate
        slippage = turnover * self.settings.paper_ledger_slippage_bps / 10_000.0
        costs = fees + slippage
        net_pnl = gross_pnl - costs
        net_r = net_pnl / position.max_loss if position.max_loss else 0.0

        self._equity += net_pnl
        self._peak_equity = max(self._peak_equity, self._equity)
        if self._peak_equity > 0:
            self._max_drawdown_percent = max(
                self._max_drawdown_percent,
                (self._peak_equity - self._equity) / self._peak_equity * 100.0,
            )
        if resolution.outcome == "TP":
            self._wins += 1
        elif resolution.outcome == "SL":
            self._losses += 1

        closed_at = resolution.outcome_candle_at or self._evaluated_at
        exit_reason = _exit_reason(position, resolution, r_multiple)
        roi_percent = self._roi_percent(position, net_pnl=net_pnl)
        fill = ActiveTradeFill(
            side=position.side,
            outcome=resolution.outcome,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity_btc=position.quantity_btc,
            gross_pnl=gross_pnl,
            fees=costs,
            net_pnl=net_pnl,
            net_r=net_r,
            opened_at=position.opened_at,
            closed_at=closed_at,
            exit_reason=exit_reason,
            roi_percent=roi_percent,
            execution_mode=position.execution_mode,
            close_order_id=close_order.order_id if close_order is not None else None,
            close_order_status=close_order.status if close_order is not None else None,
        )
        self._fills.append(fill)
        self._arm_cooldown(fill)
        self._growth.append(
            {
                "time": _iso(closed_at),
                "equity": self._equity,
                "net_pnl": net_pnl,
                "net_r": net_r,
                "return_percent": self._return_percent(),
                "outcome": resolution.outcome,
                "side": position.side,
                "exit_reason": exit_reason,
            }
        )
        self._record_settlement_event(position, fill)
        return fill

    def _estimate_net_pnl(
        self,
        position: ActiveTradePosition,
        *,
        exit_price: float,
        r_multiple: float,
    ) -> float:
        gross_pnl = r_multiple * position.max_loss
        exit_notional = position.quantity_btc * exit_price
        turnover = position.notional + abs(exit_notional)
        fees = turnover * self.settings.paper_ledger_fee_rate
        slippage = turnover * self.settings.paper_ledger_slippage_bps / 10_000.0
        return gross_pnl - fees - slippage

    def _r_multiple_at_price(
        self,
        position: ActiveTradePosition,
        exit_price: float,
    ) -> float:
        stop_distance = abs(position.entry_price - position.stop_loss)
        if stop_distance <= 0:
            return 0.0
        if position.side == "LONG":
            return (exit_price - position.entry_price) / stop_distance
        return (position.entry_price - exit_price) / stop_distance

    def _roi_percent(self, position: ActiveTradePosition, *, net_pnl: float) -> float:
        leverage = max(1, int(self.settings.futures_leverage or 1))
        margin = position.notional / leverage if position.notional else 0.0
        return net_pnl / margin * 100.0 if margin else 0.0

    def _record_open_event(self, position: ActiveTradePosition, setup: Any) -> None:
        self._append_journal_event(
            {
                "event": "OPEN",
                "symbol": self.settings.symbol,
                "exchange": self.settings.exchange,
                "side": position.side,
                "opened_at": position.opened_at,
                "candle_time": position.candle_time,
                "expires_at": position.expires_at,
                "entry_price": position.entry_price,
                "stop_loss": position.stop_loss,
                "protected_stop_loss": position.protected_stop_loss,
                "take_profit": position.take_profit,
                "quantity_btc": position.quantity_btc,
                "notional": position.notional,
                "max_loss": position.max_loss,
                "reward_to_risk": position.reward_to_risk,
                "execution_mode": position.execution_mode,
                "open_order_id": position.open_order_id,
                "open_order_status": position.open_order_status,
                "open_order_error": position.open_order_error,
                "equity_before": self._equity,
                "technical_score": getattr(setup, "technical_score", None),
                "close_price": getattr(setup, "close_price", None),
                "market_regime": getattr(setup, "market_regime", None),
                "volatility_regime": getattr(setup, "volatility_regime", None),
                "trend_range_context": getattr(setup, "trend_range_context", None),
            }
        )

    def _record_settlement_event(
        self, position: ActiveTradePosition, fill: ActiveTradeFill
    ) -> None:
        self._append_journal_event(
            {
                "event": "SETTLED",
                "symbol": self.settings.symbol,
                "exchange": self.settings.exchange,
                "side": fill.side,
                "outcome": fill.outcome,
                "opened_at": fill.opened_at,
                "closed_at": fill.closed_at,
                "candle_time": position.candle_time,
                "entry_price": fill.entry_price,
                "exit_price": fill.exit_price,
                "stop_loss": position.stop_loss,
                "protected_stop_loss": position.protected_stop_loss,
                "take_profit": position.take_profit,
                "quantity_btc": fill.quantity_btc,
                "notional": position.notional,
                "gross_pnl": fill.gross_pnl,
                "fees_and_slippage": fill.fees,
                "net_pnl": fill.net_pnl,
                "net_r": fill.net_r,
                "roi_percent": fill.roi_percent,
                "exit_reason": fill.exit_reason,
                "execution_mode": fill.execution_mode,
                "open_order_id": position.open_order_id,
                "close_order_id": fill.close_order_id,
                "close_order_status": fill.close_order_status,
                "close_order_error": fill.close_order_error,
                "equity_after": self._equity,
                "return_percent": self._return_percent(),
                "wins": self._wins,
                "losses": self._losses,
                "max_drawdown_percent": self._max_drawdown_percent,
            }
        )

    def _cooldown_decision(self, setup: Any) -> tuple[bool, str]:
        cooldown_until = self._side_cooldown_until.get(str(setup.side))
        if cooldown_until is None:
            return True, ""
        candle_time = getattr(setup, "candle_time", None)
        if candle_time is None or candle_time >= cooldown_until:
            self._side_cooldown_until.pop(str(setup.side), None)
            return True, ""
        remaining_seconds = max(0.0, (cooldown_until - candle_time).total_seconds())
        remaining_candles = int(remaining_seconds // ACTIVE_TRADER_POSITION_SECONDS) + 1
        return (
            False,
            f"{setup.side} cooldown active after a bad exit; scanning continues, "
            f"but fill waits about {remaining_candles} more 5m candle(s).",
        )

    def _arm_cooldown(self, fill: ActiveTradeFill) -> None:
        if self.settings.active_trader_cooldown_candles <= 0:
            return
        if fill.exit_reason not in COOLDOWN_EXIT_REASONS:
            return
        self._side_cooldown_until[fill.side] = fill.closed_at + timedelta(
            seconds=ACTIVE_TRADER_POSITION_SECONDS
            * self.settings.active_trader_cooldown_candles
        )

    def _append_journal_event(self, payload: dict[str, Any]) -> None:
        path = self._journal_path
        if path is None:
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"recorded_at": datetime.now(timezone.utc), **payload}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=_json_default, sort_keys=True))
            handle.write("\n")

    def _return_percent(self) -> float:
        if not self.starting_equity:
            return 0.0
        return (self._equity - self.starting_equity) / self.starting_equity * 100.0

    def _unrealized_pnl(self, market: MarketSnapshot) -> float:
        position = self._position
        if position is None or not market or market.price is None:
            return 0.0
        direction = 1.0 if position.side == "LONG" else -1.0
        return (market.price - position.entry_price) * position.quantity_btc * direction

    def _open_margin(self) -> float:
        position = self._position
        if position is None:
            return 0.0
        leverage = max(1, int(self.settings.futures_leverage or 1))
        return position.notional / leverage

    def _open_progress_percent(self, market: MarketSnapshot) -> float:
        position = self._position
        if position is None or market.price is None:
            return 0.0
        return self._favorable_progress_percent(position, market.price)

    def _favorable_progress_percent(
        self,
        position: ActiveTradePosition,
        price: float | None,
    ) -> float:
        if price is None:
            return 0.0
        if position.side == "LONG":
            denominator = position.take_profit - position.entry_price
            progress = price - position.entry_price
        else:
            denominator = position.entry_price - position.take_profit
            progress = position.entry_price - price
        if denominator <= 0:
            return 0.0
        return max(-100.0, min(100.0, progress / denominator * 100.0))

    def _distance_to_stop_percent(self, market: MarketSnapshot) -> float | None:
        position = self._position
        if position is None or market.price is None or market.price <= 0:
            return None
        stop = position.protected_stop_loss or position.stop_loss
        if position.side == "LONG":
            return (market.price - stop) / market.price * 100.0
        return (stop - market.price) / market.price * 100.0

    def _distance_to_target_percent(self, market: MarketSnapshot) -> float | None:
        position = self._position
        if position is None or market.price is None or market.price <= 0:
            return None
        if position.side == "LONG":
            return (position.take_profit - market.price) / market.price * 100.0
        return (market.price - position.take_profit) / market.price * 100.0

    def _snapshot(
        self,
        *,
        cycle: ExecutionCycle | None,
        technical: Any,
        signal: Any,
        futures: Any,
        market: MarketSnapshot,
    ) -> ActiveTraderSnapshot:
        if cycle is not None:
            self._last_cycle = cycle
        if technical is not None:
            self._last_technical = technical
        if signal is not None:
            self._last_signal = signal
        if futures is not None:
            self._last_futures = futures
        cycle = cycle if cycle is not None else self._last_cycle
        technical = technical if technical is not None else self._last_technical
        signal = signal if signal is not None else self._last_signal
        futures = futures if futures is not None else self._last_futures
        self._record_cycle_point(cycle, technical, futures)
        closed_directional = self._wins + self._losses
        unrealized_pnl = self._unrealized_pnl(market)
        open_margin = self._open_margin()
        open_total_pnl = self._equity - self.starting_equity + unrealized_pnl
        account = ActiveTraderAccount(
            starting_equity=self.starting_equity,
            equity=self._equity,
            realized_pnl=self._equity - self.starting_equity,
            return_percent=self._return_percent(),
            peak_equity=self._peak_equity,
            max_drawdown_percent=self._max_drawdown_percent,
            closed_trades=len(self._fills),
            wins=self._wins,
            losses=self._losses,
            win_rate=(
                self._wins / closed_directional if closed_directional else None
            ),
            open_position=self._position,
            unrealized_pnl=unrealized_pnl,
            unrealized_roi_percent=(
                unrealized_pnl / open_margin * 100.0 if open_margin else 0.0
            ),
            open_margin=open_margin,
            open_total_pnl=open_total_pnl,
            open_total_return_percent=(
                open_total_pnl / self.starting_equity * 100.0
                if self.starting_equity
                else 0.0
            ),
            open_progress_percent=self._open_progress_percent(market),
            open_distance_to_stop_percent=self._distance_to_stop_percent(market),
            open_distance_to_target_percent=self._distance_to_target_percent(market),
            mark_price=market.price,
        )
        return ActiveTraderSnapshot(
            enabled=True,
            symbol=self.settings.symbol,
            interval_seconds=self.settings.active_trader_refresh_seconds,
            evaluated_at=self._evaluated_at,
            account=account,
            execution_cycle=cycle,
            technical=technical,
            signal=signal,
            futures=futures,
            growth_curve=tuple(self._growth[-GROWTH_CURVE_LIMIT:]),
            recent_fills=tuple(self._fills[-RECENT_FILLS_LIMIT:]),
            cycle_history=tuple(
                self._cycle_history[-ACTIVE_TRADER_CYCLE_HISTORY_LIMIT:]
            ),
            last_action=self._last_action,
            last_detail=self._last_detail,
            execution_mode=self.execution_mode,
            execution_status=self._execution_status(),
            cooldown_detail=self._cooldown_detail(),
            scam_alert=_scam_alert(cycle),
            disclaimer=self._disclaimer(),
        )

    def _record_cycle_point(
        self,
        cycle: ExecutionCycle | None,
        technical: Any,
        futures: Any,
    ) -> None:
        if cycle is None:
            return
        stages = {stage.name: stage for stage in cycle.stages}
        side = str(getattr(futures, "side", "") or "FLAT")
        point = ActiveTraderCyclePoint(
            recorded_at=self._evaluated_at,
            status=cycle.status,
            side=side,
            action=self._last_action,
            technical_score=float(getattr(technical, "score", 0.0) or 0.0),
            scam_status=stages.get("Scam detect", ExecutionStage("", "-", "")).status,
            validate_status=stages.get("Validate", ExecutionStage("", "-", "")).status,
            size_status=stages.get("Size", ExecutionStage("", "-", "")).status,
            fill_status=stages.get("Fill", ExecutionStage("", "-", "")).status,
            settle_status=stages.get("Settle", ExecutionStage("", "-", "")).status,
            detail=self._last_detail,
        )
        previous = self._cycle_history[-1] if self._cycle_history else None
        if (
            previous is not None
            and previous.status == point.status
            and previous.action == point.action
            and previous.side == point.side
            and previous.fill_status == point.fill_status
            and previous.detail == point.detail
        ):
            return
        self._cycle_history.append(point)
        if len(self._cycle_history) > ACTIVE_TRADER_CYCLE_HISTORY_LIMIT:
            del self._cycle_history[:-ACTIVE_TRADER_CYCLE_HISTORY_LIMIT]

    def _cooldown_detail(self) -> str:
        if not self._side_cooldown_until:
            return ""
        parts = []
        for side, until in sorted(self._side_cooldown_until.items()):
            parts.append(f"{side} until {_iso(until)}")
        return "; ".join(parts)

    def _prepare_demo_open(
        self,
        position: ActiveTradePosition,
    ) -> tuple[ActiveTradePosition, str | None]:
        if self.execution_mode != "binance_demo":
            return position, None
        if self._demo_client is None:
            return replace(position, open_order_error=self._demo_error), self._demo_error
        try:
            order = self._demo_client.open_market_position(
                symbol=self.settings.symbol,
                side=position.side,
                quantity_btc=position.quantity_btc,
                leverage=self.settings.futures_leverage,
            )
        except BinanceDemoError as exc:
            return replace(position, open_order_error=str(exc)), str(exc)
        return (
            replace(
                position,
                open_order_id=order.order_id,
                open_order_status=order.status,
                open_order_error=None,
            ),
            None,
        )

    def _prepare_demo_close(
        self,
        position: ActiveTradePosition,
    ) -> tuple[BinanceDemoOrder | None, str | None]:
        if position.execution_mode != "binance_demo":
            return None, None
        if self._demo_client is None:
            return None, self._demo_error
        try:
            return (
                self._demo_client.close_market_position(
                    symbol=self.settings.symbol,
                    side=position.side,
                    quantity_btc=position.quantity_btc,
                ),
                None,
            )
        except BinanceDemoError as exc:
            return None, str(exc)

    def _open_detail(self, position: ActiveTradePosition) -> str:
        if position.execution_mode == "binance_demo":
            return (
                f"Binance Demo market-filled {position.side} at "
                f"${position.entry_price:,.2f} "
                f"(order {position.open_order_id or 'submitted'})."
            )
        return f"Paper-filled {position.side} at ${position.entry_price:,.2f}."

    def _execution_status(self) -> str:
        if self.execution_mode != "binance_demo":
            return "paper simulation"
        if self._demo_client is None:
            return f"binance demo unavailable: {self._demo_error}"
        return "binance demo market orders enabled"

    def _disclaimer(self) -> str:
        if self.execution_mode == "binance_demo":
            return (
                "Binance Demo Trading only; no live exchange orders; not financial advice"
            )
        return "paper only; no order placed; not financial advice; session simulation"


def _cycle_headline(cycle: ExecutionCycle | None) -> str:
    if cycle is None or not cycle.stages:
        return "No directional setup this cycle."
    for stage in cycle.stages:
        if stage.status == "BLOCKED":
            return f"{stage.name} blocked: {stage.detail}"
    return cycle.stages[0].detail


def _settle_cycle(cycle: ExecutionCycle | None, detail: str) -> ExecutionCycle | None:
    if cycle is None:
        return None
    stages = tuple(
        ExecutionStage("Settle", "PASS", detail)
        if stage.name == "Settle" and stage.status == "PENDING"
        else stage
        for stage in cycle.stages
    )
    return ExecutionCycle(status="SETTLED", stages=stages)


def _cooldown_cycle(cycle: ExecutionCycle | None, detail: str) -> ExecutionCycle | None:
    if cycle is None:
        return None
    stages = []
    for stage in cycle.stages:
        if stage.name == "Fill" and stage.status == "PENDING":
            stages.append(ExecutionStage("Fill", "COOLDOWN", detail))
        elif stage.name == "Settle" and stage.status == "PENDING":
            stages.append(ExecutionStage("Settle", "SKIPPED", detail))
        else:
            stages.append(stage)
    return ExecutionCycle(status="COOLDOWN", stages=tuple(stages))


def _scam_alert(cycle: ExecutionCycle | None) -> str:
    if cycle is None:
        return ""
    for stage in cycle.stages:
        if stage.name == "Scam detect" and stage.status == "BLOCKED":
            return f"Alert: scam/manipulation risk detected. {stage.detail}"
    return ""


def _favorable_candle_price(
    position: ActiveTradePosition,
    candle: dict[str, Any],
) -> float | None:
    key = "high" if position.side == "LONG" else "low"
    value = candle.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exit_reason(
    position: ActiveTradePosition,
    resolution: PaperSetupResolution,
    r_multiple: float,
) -> str:
    if resolution.outcome == OUTCOME_TP:
        if r_multiple + 1e-9 < position.reward_to_risk:
            progress = (
                r_multiple / position.reward_to_risk * 100.0
                if position.reward_to_risk
                else 0.0
            )
            if progress >= 75.0:
                return "PROGRESS_TP"
            return "EARLY_TP"
        return "TARGET_HIT"
    if resolution.outcome == OUTCOME_SL:
        stop = position.protected_stop_loss or position.stop_loss
        if position.original_stop_loss is not None and stop != position.original_stop_loss:
            return "PROTECTED_STOP"
        return "STOP_LOSS"
    if resolution.outcome == OUTCOME_EXPIRED:
        return "EXPIRED"
    return resolution.outcome


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _force_active_signal(signal: Any, technical: Any) -> Any:
    score = _active_directional_score(technical)
    forced_signal = "STRONG BUY" if score >= 0 else "STRONG SELL"
    forced_score = max(0.01, abs(score)) if score >= 0 else -max(0.01, abs(score))
    return replace(
        signal,
        signal=forced_signal,
        raw_score=forced_score,
        score=forced_score,
        technical_contribution=forced_score,
        sentiment_contribution=0.0,
        macro_contribution=0.0,
        risk_multiplier=1.0,
    )


def _active_directional_score(technical: Any) -> float:
    score = float(getattr(technical, "score", 0.0) or 0.0)
    if score:
        return score

    macd_histogram = float(getattr(technical, "macd_histogram", 0.0) or 0.0)
    if macd_histogram:
        return macd_histogram

    ema20 = float(getattr(technical, "ema20", 0.0) or 0.0)
    ema50 = float(getattr(technical, "ema50", 0.0) or 0.0)
    if ema20 != ema50:
        return ema20 - ema50

    open_price = getattr(technical, "open", None)
    close_price = getattr(technical, "close", None)
    if open_price is not None and close_price is not None and close_price != open_price:
        return float(close_price) - float(open_price)

    return 0.01
