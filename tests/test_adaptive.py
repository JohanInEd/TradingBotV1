from datetime import datetime, timezone

from btc_trading_bot.adaptive import resolve_signal_profile
from btc_trading_bot.config import Settings


def _context(structure: str, volatility: str = "NORMAL VOLATILITY"):
    from btc_trading_bot.models import MarketContext

    return MarketContext(
        volatility_regime=volatility,
        structure_regime=structure,
        atr_percent=1.0,
        realized_volatility_percent=1.0,
        bollinger_width_percent=5.0,
        range_position_percent=50.0,
        trend_strength_percent=2.5,
        reason="test",
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_baseline_profile_without_context_or_when_disabled() -> None:
    settings = Settings()

    unchanged, profile = resolve_signal_profile(settings, None)
    assert unchanged is settings
    assert profile.name == "baseline"
    assert not profile.adaptive

    disabled = Settings(adaptive_weights_enabled=False)
    unchanged, profile = resolve_signal_profile(disabled, _context("TRENDING UP"))
    assert unchanged is disabled
    assert profile.name == "baseline"


def test_trending_regime_shifts_weight_to_trend_confirmation() -> None:
    settings = Settings()

    adjusted, profile = resolve_signal_profile(settings, _context("TRENDING UP"))

    assert profile.name == "trend-following"
    assert profile.adaptive
    assert adjusted.primary_timeframe_weight == 0.55
    assert adjusted.daily_timeframe_weight == 0.35
    assert adjusted.entry_timeframe_weight == 0.10
    # Thresholds stay at the configured baseline while trending.
    assert adjusted.buy_threshold == settings.buy_threshold
    # Risk sizing settings are untouched.
    assert adjusted.risk_per_trade == settings.risk_per_trade
    assert adjusted.stop_loss_percent == settings.stop_loss_percent


def test_range_regime_raises_thresholds_and_entry_weight() -> None:
    adjusted, profile = resolve_signal_profile(
        Settings(), _context("RANGE COMPRESSION")
    )

    assert profile.name == "range-caution"
    assert adjusted.buy_threshold == 0.70
    assert adjusted.sell_threshold == -0.70
    assert adjusted.entry_timeframe_weight == 0.30


def test_high_volatility_guard_raises_confirmation_bar() -> None:
    adjusted, profile = resolve_signal_profile(
        Settings(), _context("TRENDING DOWN", volatility="HIGH VOLATILITY")
    )

    assert profile.name == "trend-following+vol-guard"
    assert adjusted.buy_threshold == 0.75
    assert adjusted.sell_threshold == -0.75

    vol_only, profile_only = resolve_signal_profile(
        Settings(), _context("MID-RANGE", volatility="HIGH VOLATILITY")
    )
    assert profile_only.name == "range-caution+vol-guard"
    assert vol_only.buy_threshold == 0.75
