from __future__ import annotations

from dataclasses import replace

from btc_trading_bot.config import Settings
from btc_trading_bot.models import MarketContext, SignalProfile

TRENDING_REGIMES = {"TRENDING UP", "TRENDING DOWN"}
RANGE_REGIMES = {"RANGE COMPRESSION", "MID-RANGE", "UPPER RANGE", "LOWER RANGE"}
HIGH_VOLATILITY_THRESHOLD = 0.75
RANGE_THRESHOLD = 0.70


def resolve_signal_profile(
    settings: Settings,
    market_context: MarketContext | None,
) -> tuple[Settings, SignalProfile]:
    """Condition signal weights and thresholds on the current market regime.

    Trend-following confirmation (4h strategy + daily trend) earns more weight
    while a trend is in force; inside ranges the bar for a directional signal
    rises and 1h entry timing matters more; high volatility always raises the
    confirmation bar. Position sizing and risk settings are never touched.
    """
    baseline = _profile_from(settings, name="baseline", reason=(
        "Static configured weights and thresholds."
    ))
    if not settings.adaptive_weights_enabled or market_context is None:
        return settings, baseline

    structure = market_context.structure_regime
    volatility = market_context.volatility_regime
    name = "baseline"
    reason_parts: list[str] = []
    buy_threshold = settings.buy_threshold
    sell_threshold = settings.sell_threshold
    primary_weight = settings.primary_timeframe_weight
    daily_weight = settings.daily_timeframe_weight
    hourly_weight = settings.entry_timeframe_weight

    if structure in TRENDING_REGIMES:
        name = "trend-following"
        primary_weight, daily_weight, hourly_weight = 0.55, 0.35, 0.10
        reason_parts.append(
            f"{structure.lower()} favors 4h strategy and daily trend weight"
        )
    elif structure in RANGE_REGIMES:
        name = "range-caution"
        primary_weight, daily_weight, hourly_weight = 0.50, 0.20, 0.30
        buy_threshold = max(buy_threshold, RANGE_THRESHOLD)
        sell_threshold = min(sell_threshold, -RANGE_THRESHOLD)
        reason_parts.append(
            f"{structure.lower()} raises the confirmation bar and 1h entry weight"
        )

    if volatility == "HIGH VOLATILITY":
        name = f"{name}+vol-guard" if name != "baseline" else "vol-guard"
        buy_threshold = max(buy_threshold, HIGH_VOLATILITY_THRESHOLD)
        sell_threshold = min(sell_threshold, -HIGH_VOLATILITY_THRESHOLD)
        reason_parts.append(
            "high volatility requires stronger confluence before a signal"
        )

    if name == "baseline":
        return settings, baseline

    adjusted = replace(
        settings,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        primary_timeframe_weight=primary_weight,
        daily_timeframe_weight=daily_weight,
        entry_timeframe_weight=hourly_weight,
    )
    return adjusted, _profile_from(
        adjusted,
        name=name,
        reason="; ".join(reason_parts).capitalize() + ".",
        adaptive=True,
    )


def _profile_from(
    settings: Settings,
    *,
    name: str,
    reason: str,
    adaptive: bool = False,
) -> SignalProfile:
    return SignalProfile(
        name=name,
        reason=reason,
        buy_threshold=settings.buy_threshold,
        sell_threshold=settings.sell_threshold,
        primary_weight=settings.primary_timeframe_weight,
        daily_weight=settings.daily_timeframe_weight,
        hourly_weight=settings.entry_timeframe_weight,
        adaptive=adaptive,
    )
