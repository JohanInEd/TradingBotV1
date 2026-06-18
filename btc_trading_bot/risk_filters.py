from __future__ import annotations

from dataclasses import replace

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    FuturesMetrics,
    FuturesRecommendation,
    MarketContext,
    ProbabilityForecast,
    ShakeoutAnalysis,
    TradeFilterResult,
)


def apply_do_not_trade_filters(
    futures: FuturesRecommendation,
    settings: Settings,
    *,
    probability_forecast: ProbabilityForecast | None = None,
    market_context: MarketContext | None = None,
    shakeout: ShakeoutAnalysis | None = None,
    futures_metrics: FuturesMetrics | None = None,
) -> tuple[FuturesRecommendation, TradeFilterResult]:
    if not settings.do_not_trade_filters_enabled:
        return futures, TradeFilterResult(
            status="DISABLED",
            allowed=futures.side in {"LONG", "SHORT"},
            original_action=futures.action,
            reasons=("Do-not-trade filters are disabled.",),
        )

    if futures.side not in {"LONG", "SHORT"}:
        return futures, TradeFilterResult(
            status="NO SETUP",
            allowed=False,
            original_action=futures.action,
            reasons=("No confirmed futures setup to filter.",),
        )

    reasons: list[str] = []
    _check_probability(futures, settings, probability_forecast, reasons)
    _check_market_context(futures, settings, market_context, reasons)
    _check_shakeout(futures, shakeout, reasons)
    _check_futures_metrics(futures, settings, futures_metrics, reasons)

    if not reasons:
        return futures, TradeFilterResult(
            status="PASS",
            allowed=True,
            original_action=futures.action,
            reasons=("All active do-not-trade filters passed.",),
        )

    blocked = replace(
        futures,
        action="STAY FLAT",
        side="FLAT",
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        quantity_btc=0.0,
        notional=0.0,
        max_loss=0.0,
        reason=(
            f"Do-not-trade filter blocked {futures.action}: "
            + " ".join(reasons)
        ),
    )
    return blocked, TradeFilterResult(
        status="BLOCKED",
        allowed=False,
        original_action=futures.action,
        reasons=tuple(reasons),
    )


def _check_probability(
    futures: FuturesRecommendation,
    settings: Settings,
    probability: ProbabilityForecast | None,
    reasons: list[str],
) -> None:
    if probability is None:
        if settings.trade_filter_require_probability:
            reasons.append("Probability forecast is unavailable.")
        return

    if probability.sample_size < settings.trade_filter_min_probability_samples:
        reasons.append(
            "Probability sample is too small "
            f"({probability.sample_size}/{settings.trade_filter_min_probability_samples})."
        )
        return

    if futures.side == "LONG":
        expected_r = probability.expected_long_r
        tp_probability = probability.long_tp_before_sl_probability
        sl_probability = probability.long_sl_before_tp_probability
    else:
        expected_r = probability.expected_short_r
        tp_probability = probability.short_tp_before_sl_probability
        sl_probability = probability.short_sl_before_tp_probability

    if expected_r < settings.trade_filter_min_expected_r:
        reasons.append(
            f"{futures.side} expected R is {expected_r:+.2f}, below "
            f"{settings.trade_filter_min_expected_r:+.2f}."
        )
    if tp_probability <= sl_probability:
        reasons.append(
            f"{futures.side} TP-before-SL odds are not favorable "
            f"({tp_probability:.0%} TP vs {sl_probability:.0%} SL)."
        )


def _check_market_context(
    futures: FuturesRecommendation,
    settings: Settings,
    context: MarketContext | None,
    reasons: list[str],
) -> None:
    if context is None:
        return

    if context.atr_percent >= settings.trade_filter_max_atr_percent:
        reasons.append(
            f"ATR is {context.atr_percent:.2f}%, above "
            f"{settings.trade_filter_max_atr_percent:.2f}%."
        )

    extreme = settings.trade_filter_range_extreme_percent
    lower_extreme = 100.0 - extreme
    if futures.side == "LONG":
        if context.structure_regime == "TRENDING DOWN":
            reasons.append("Market structure is trending down against a LONG.")
        if context.range_position_percent >= extreme:
            reasons.append(
                f"LONG would chase the upper range "
                f"({context.range_position_percent:.0f}%)."
            )
    else:
        if context.structure_regime == "TRENDING UP":
            reasons.append("Market structure is trending up against a SHORT.")
        if context.range_position_percent <= lower_extreme:
            reasons.append(
                f"SHORT would chase the lower range "
                f"({context.range_position_percent:.0f}%)."
            )


def _check_shakeout(
    futures: FuturesRecommendation,
    shakeout: ShakeoutAnalysis | None,
    reasons: list[str],
) -> None:
    if shakeout is None or shakeout.status != "HIGH":
        return
    direction = shakeout.direction.upper()
    if futures.side == "LONG" and "DOWNSIDE" in direction:
        reasons.append("High downside shakeout risk conflicts with LONG.")
    elif futures.side == "SHORT" and "UPSIDE" in direction:
        reasons.append("High upside shakeout risk conflicts with SHORT.")
    elif "TWO" in direction or "BOTH" in direction:
        reasons.append("High two-sided shakeout risk is active.")


def _check_futures_metrics(
    futures: FuturesRecommendation,
    settings: Settings,
    metrics: FuturesMetrics | None,
    reasons: list[str],
) -> None:
    if metrics is None:
        return
    funding = metrics.funding_rate
    ratio = metrics.long_short_ratio
    if funding is None or ratio is None:
        return

    funding_extreme = settings.trade_filter_funding_extreme
    ratio_extreme = settings.trade_filter_long_short_extreme
    lower_ratio_extreme = 1.0 / ratio_extreme if ratio_extreme else 0.0

    if futures.side == "LONG" and funding >= funding_extreme and ratio >= ratio_extreme:
        reasons.append(
            f"Long crowding is stretched: funding {funding:.4%}, "
            f"long/short {ratio:.2f}."
        )
    elif (
        futures.side == "SHORT"
        and funding <= -funding_extreme
        and ratio <= lower_ratio_extreme
    ):
        reasons.append(
            f"Short crowding is stretched: funding {funding:.4%}, "
            f"long/short {ratio:.2f}."
        )
