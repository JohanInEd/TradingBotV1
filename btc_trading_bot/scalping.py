from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from btc_trading_bot.config import Settings
from btc_trading_bot.futures import build_futures_recommendation
from btc_trading_bot.indicators import analyze_technicals
from btc_trading_bot.market_context import analyze_market_context
from btc_trading_bot.models import (
    Evaluation,
    ExecutionCycle,
    ExecutionStage,
    FuturesRecommendation,
    MarketSnapshot,
    PaperSetup,
    ScalpingEvaluation,
    ShakeoutAnalysis,
    TradeFilterResult,
)
from btc_trading_bot.news import neutral_macro, neutral_sentiment
from btc_trading_bot.paper_setups import build_current_paper_setup
from btc_trading_bot.risk_filters import apply_do_not_trade_filters
from btc_trading_bot.strategy import calculate_signal

SCALPING_TIMEFRAME = "5m"
SCALPING_LABEL = "5m scalp setup"
DIRECTIONAL_ACTIONS = frozenset({"GO LONG", "GO SHORT"})


def scalping_settings(settings: Settings) -> Settings:
    """Purely-technical, tight-risk settings for the 5-minute scalping system.

    Scalping is deliberately independent of the 4h-anchored signal: it skips
    news/macro sentiment (too slow-moving to matter on a 5-minute horizon)
    and uses a much tighter stop/target than the primary swing settings,
    which would rarely be hit by 5-minute price action.
    """
    return replace(
        settings,
        technical_weight=1.0,
        sentiment_weight=0.0,
        macro_weight=0.0,
        buy_threshold=settings.scalping_buy_threshold,
        sell_threshold=settings.scalping_sell_threshold,
        stop_loss_percent=settings.scalping_stop_loss_percent,
        reward_to_risk=settings.scalping_reward_to_risk,
        risk_per_trade=settings.scalping_risk_per_trade,
        paper_setup_horizon_hours=settings.scalping_horizon_hours,
    )


def evaluate_scalping(
    candles: Any,
    market: MarketSnapshot,
    settings: Settings,
    *,
    shakeout: ShakeoutAnalysis | None = None,
) -> ScalpingEvaluation:
    """Build a closed-5m-candle scalping signal, futures plan, and paper setup."""
    mode_settings = scalping_settings(settings)
    technical = analyze_technicals(candles)
    try:
        context = analyze_market_context(candles)
    except Exception:
        context = None
    signal = calculate_signal(
        technical, neutral_sentiment(), neutral_macro(), mode_settings
    )
    futures = build_futures_recommendation(signal, market, mode_settings)
    futures, trade_filter = apply_do_not_trade_filters(
        futures,
        mode_settings,
        probability_forecast=None,
        market_context=context,
        shakeout=shakeout,
        futures_metrics=None,
    )
    evaluated_at = datetime.now(timezone.utc)
    paper_setup = build_current_paper_setup(
        futures=futures,
        technical=technical,
        evaluated_at=evaluated_at,
        settings=mode_settings,
        market_context=context,
        probability_forecast=None,
    )
    execution_cycle = build_execution_cycle(
        trade_filter=trade_filter,
        futures=futures,
        shakeout=shakeout,
        paper_setup=paper_setup,
    )
    return ScalpingEvaluation(
        technical=technical,
        market_context=context,
        signal=signal,
        futures=futures,
        trade_filter=trade_filter,
        paper_setup=paper_setup,
        evaluated_at=evaluated_at,
        execution_cycle=execution_cycle,
    )


def build_execution_cycle(
    *,
    trade_filter: TradeFilterResult,
    futures: FuturesRecommendation,
    shakeout: ShakeoutAnalysis | None,
    paper_setup: PaperSetup | None,
) -> ExecutionCycle:
    """Model the paper-trade lifecycle for the current scalp setup as five
    stages: scam detect (shakeout/microstructure risk), validate (do-not-trade
    filters), size (position sizing), fill (paper entry), and settle (journal
    outcome). Each stage short-circuits the ones after it once blocked.
    """
    if trade_filter.original_action not in DIRECTIONAL_ACTIONS:
        idle_reason = "No directional setup this cycle."
        stages = (
            ExecutionStage("Scam detect", "SKIPPED", idle_reason),
            ExecutionStage("Validate", "SKIPPED", idle_reason),
            ExecutionStage("Size", "SKIPPED", idle_reason),
            ExecutionStage("Fill", "SKIPPED", idle_reason),
            ExecutionStage("Settle", "SKIPPED", "No open position to settle."),
        )
        return ExecutionCycle(status="IDLE", stages=stages)

    if shakeout is None:
        scam_stage = ExecutionStage(
            "Scam detect",
            "PENDING",
            "Shakeout/microstructure data is not available yet.",
        )
    elif shakeout.status == "HIGH":
        scam_stage = ExecutionStage(
            "Scam detect",
            "BLOCKED",
            f"High shakeout risk ({shakeout.direction}); treated as possible manipulation.",
        )
    else:
        scam_stage = ExecutionStage(
            "Scam detect",
            "PASS",
            f"Shakeout risk {shakeout.status.lower()}; no manipulation signal detected.",
        )

    if scam_stage.status == "BLOCKED":
        skip = "Skipped after scam-detect block."
        return ExecutionCycle(
            status="BLOCKED",
            stages=(
                scam_stage,
                ExecutionStage("Validate", "SKIPPED", skip),
                ExecutionStage("Size", "SKIPPED", skip),
                ExecutionStage("Fill", "SKIPPED", skip),
                ExecutionStage("Settle", "SKIPPED", "No open position to settle."),
            ),
        )

    if trade_filter.status == "BLOCKED":
        validate_stage = ExecutionStage(
            "Validate",
            "BLOCKED",
            " ".join(trade_filter.reasons) or "Do-not-trade filters blocked this setup.",
        )
    elif trade_filter.status == "DISABLED":
        validate_stage = ExecutionStage(
            "Validate", "PASS", "Do-not-trade filters are disabled."
        )
    else:
        validate_stage = ExecutionStage(
            "Validate", "PASS", "All active do-not-trade filters passed."
        )

    if validate_stage.status == "BLOCKED":
        skip = "Skipped after validate block."
        return ExecutionCycle(
            status="BLOCKED",
            stages=(
                scam_stage,
                validate_stage,
                ExecutionStage("Size", "SKIPPED", skip),
                ExecutionStage("Fill", "SKIPPED", skip),
                ExecutionStage("Settle", "SKIPPED", "No open position to settle."),
            ),
        )

    if futures.side in {"LONG", "SHORT"} and futures.quantity_btc > 0:
        size_stage = ExecutionStage(
            "Size",
            "PASS",
            f"{futures.quantity_btc:.4f} BTC (~${futures.notional:,.2f}), "
            f"max loss ${futures.max_loss:,.2f}.",
        )
    else:
        size_stage = ExecutionStage("Size", "BLOCKED", "Computed position size is zero.")

    if size_stage.status == "BLOCKED":
        skip = "Skipped after size block."
        return ExecutionCycle(
            status="BLOCKED",
            stages=(
                scam_stage,
                validate_stage,
                size_stage,
                ExecutionStage("Fill", "SKIPPED", skip),
                ExecutionStage("Settle", "SKIPPED", "No open position to settle."),
            ),
        )

    if paper_setup is not None:
        fill_stage = ExecutionStage(
            "Fill",
            "PENDING",
            "Paper fill candidate ready; confirming no duplicate open position.",
        )
        settle_stage = ExecutionStage("Settle", "PENDING", "Awaiting fill confirmation.")
        status = "PENDING"
    else:
        fill_stage = ExecutionStage("Fill", "BLOCKED", "Paper setup could not be built.")
        settle_stage = ExecutionStage("Settle", "SKIPPED", "No open position to settle.")
        status = "BLOCKED"

    return ExecutionCycle(
        status=status,
        stages=(scam_stage, validate_stage, size_stage, fill_stage, settle_stage),
    )


def finalize_execution_cycle(
    cycle: ExecutionCycle | None,
    *,
    filled: bool,
    detail: str,
) -> ExecutionCycle | None:
    """Resolve the pending Fill/Settle stages once the journal confirms
    whether this setup was actually opened (vs. blocked by an already-open
    scalp position for the symbol).
    """
    if cycle is None:
        return None

    stages = []
    for stage in cycle.stages:
        if stage.name == "Fill" and stage.status == "PENDING":
            stages.append(
                ExecutionStage("Fill", "PASS" if filled else "SKIPPED", detail)
            )
        elif stage.name == "Settle" and stage.status == "PENDING":
            if filled:
                stages.append(
                    ExecutionStage(
                        "Settle",
                        "PENDING",
                        "Open; resolves as TP, SL, or EXPIRED from future closed 5m candles.",
                    )
                )
            else:
                stages.append(ExecutionStage("Settle", "SKIPPED", detail))
        else:
            stages.append(stage)

    if filled:
        status = "FILLED"
    elif any(stage.status == "BLOCKED" for stage in stages):
        status = "BLOCKED"
    else:
        status = "SKIPPED"
    return ExecutionCycle(status=status, stages=tuple(stages))


def to_journal_evaluation(
    result: ScalpingEvaluation, market: MarketSnapshot
) -> Evaluation:
    """Wrap a ScalpingEvaluation so it can reuse PaperSetupJournal.record()."""
    return Evaluation(
        market=market,
        technical=result.technical,
        sentiment=neutral_sentiment(),
        macro=neutral_macro(),
        signal=result.signal,
        evaluated_at=result.evaluated_at,
        next_analysis_at=result.evaluated_at,
        futures=result.futures,
        trade_filter=result.trade_filter,
        paper_setup=result.paper_setup,
        market_context=result.market_context,
    )
