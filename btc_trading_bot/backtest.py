from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

from btc_trading_bot.indicators import (
    _clamp,
    _ema_signal,
    _macd_signal,
    _rsi_signal,
)
from btc_trading_bot.models import ProbabilityForecast


class ProbabilityBacktestError(RuntimeError):
    """Raised when historical probability cannot be estimated."""


@dataclass(frozen=True, slots=True)
class ProbabilityBacktestSettings:
    horizon_hours: int = 24
    horizon_candles: int = 6
    lookback_candles: int = 220
    min_samples: int = 30
    max_samples: int = 120


@dataclass(frozen=True, slots=True)
class _Setup:
    index: int
    close: float
    score: float
    rsi14: float
    ema_spread_percent: float
    macd_histogram_percent: float


@dataclass(frozen=True, slots=True)
class _PathOutcome:
    result: str
    r_multiple: float


def forecast_probability(
    candles: pd.DataFrame,
    settings: ProbabilityBacktestSettings | None = None,
    *,
    stop_loss_percent: float = 0.015,
    reward_to_risk: float = 2.0,
) -> ProbabilityForecast:
    settings = settings or ProbabilityBacktestSettings()
    _validate_settings(settings, stop_loss_percent, reward_to_risk)
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        raise ProbabilityBacktestError(
            "Candles must include timestamp, open, high, low, and close"
        )

    data = candles.tail(
        settings.lookback_candles + settings.horizon_candles + 80
    ).copy()
    data = data.sort_values("timestamp").reset_index(drop=True)
    for column in ("open", "high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"]).reset_index(
        drop=True
    )
    if len(data) < max(60, settings.horizon_candles + 30):
        raise ProbabilityBacktestError(
            "At least 60 valid candles are required for probability backtest"
        )

    data = _with_indicators(data)
    current = _setup_from_index(data, len(data) - 1)
    if current is None:
        raise ProbabilityBacktestError("Latest setup has incomplete indicators")

    candidates: list[tuple[float, _Setup]] = []
    first_index = 1
    last_index = len(data) - settings.horizon_candles
    for index in range(first_index, last_index):
        setup = _setup_from_index(data, index)
        if setup is None:
            continue
        distance = _setup_distance(current, setup)
        candidates.append((distance, setup))

    if not candidates:
        raise ProbabilityBacktestError("No historical forward windows were available")

    candidates.sort(key=lambda item: item[0])
    selected = [
        setup for _, setup in candidates[: min(settings.max_samples, len(candidates))]
    ]
    if len(selected) < settings.min_samples:
        selected = [setup for _, setup in candidates]

    up = down = flat = 0
    long_target = long_stop = 0
    short_target = short_stop = 0
    long_r_values: list[float] = []
    short_r_values: list[float] = []
    returns: list[float] = []

    for setup in selected:
        future = data.iloc[
            setup.index + 1 : setup.index + 1 + settings.horizon_candles
        ]
        if len(future) < settings.horizon_candles:
            continue

        horizon_close = float(future["close"].iloc[-1])
        forward_return = horizon_close / setup.close - 1.0
        returns.append(forward_return)
        if forward_return > 0:
            up += 1
        elif forward_return < 0:
            down += 1
        else:
            flat += 1

        long_outcome = _long_path_outcome(
            future,
            setup.close,
            stop_loss_percent=stop_loss_percent,
            reward_to_risk=reward_to_risk,
        )
        short_outcome = _short_path_outcome(
            future,
            setup.close,
            stop_loss_percent=stop_loss_percent,
            reward_to_risk=reward_to_risk,
        )
        long_r_values.append(long_outcome.r_multiple)
        short_r_values.append(short_outcome.r_multiple)
        if long_outcome.result == "target":
            long_target += 1
        elif long_outcome.result == "stop":
            long_stop += 1
        if short_outcome.result == "target":
            short_target += 1
        elif short_outcome.result == "stop":
            short_stop += 1

    sample_size = len(returns)
    if sample_size == 0:
        raise ProbabilityBacktestError("No complete probability samples were available")

    return ProbabilityForecast(
        horizon_hours=settings.horizon_hours,
        up_probability=up / sample_size,
        down_probability=down / sample_size,
        flat_probability=flat / sample_size,
        long_tp_before_sl_probability=long_target / sample_size,
        long_sl_before_tp_probability=long_stop / sample_size,
        short_tp_before_sl_probability=short_target / sample_size,
        short_sl_before_tp_probability=short_stop / sample_size,
        expected_long_r=sum(long_r_values) / sample_size,
        expected_short_r=sum(short_r_values) / sample_size,
        average_forward_return_percent=(sum(returns) / sample_size) * 100.0,
        sample_size=sample_size,
        candidate_count=len(candidates),
        confidence=_confidence(sample_size),
        method=(
            "Nearest historical 4h technical setups; direction uses horizon "
            "close, TP/SL uses conservative intrabar path assumptions."
        ),
        generated_at=datetime.now(timezone.utc),
    )


def _validate_settings(
    settings: ProbabilityBacktestSettings,
    stop_loss_percent: float,
    reward_to_risk: float,
) -> None:
    if settings.horizon_candles <= 0:
        raise ProbabilityBacktestError("Horizon candles must be positive")
    if settings.lookback_candles <= settings.horizon_candles:
        raise ProbabilityBacktestError("Lookback must be larger than the horizon")
    if settings.max_samples <= 0:
        raise ProbabilityBacktestError("Maximum samples must be positive")
    if stop_loss_percent <= 0:
        raise ProbabilityBacktestError("Stop-loss percent must be positive")
    if reward_to_risk <= 0:
        raise ProbabilityBacktestError("Reward-to-risk must be positive")


def _with_indicators(data: pd.DataFrame) -> pd.DataFrame:
    close = pd.to_numeric(data["close"], errors="coerce")
    data = data.copy()
    data["ema20"] = EMAIndicator(close=close, window=20).ema_indicator()
    data["ema50"] = EMAIndicator(close=close, window=50).ema_indicator()
    data["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_histogram"] = macd.macd_diff()
    return data


def _setup_from_index(data: pd.DataFrame, index: int) -> _Setup | None:
    current = data.iloc[index]
    previous = data.iloc[index - 1]
    values = (
        current["close"],
        current["ema20"],
        current["ema50"],
        current["rsi14"],
        current["macd"],
        current["macd_signal"],
        current["macd_histogram"],
        previous["ema20"],
        previous["ema50"],
        previous["macd"],
        previous["macd_signal"],
        previous["macd_histogram"],
    )
    if any(pd.isna(value) or not math.isfinite(float(value)) for value in values):
        return None

    _, ema_score = _ema_signal(current, previous)
    _, rsi_score = _rsi_signal(float(current["rsi14"]))
    _, macd_score = _macd_signal(current, previous)
    score = _clamp(0.40 * ema_score + 0.25 * rsi_score + 0.35 * macd_score)
    close = float(current["close"])
    if close <= 0:
        return None
    return _Setup(
        index=index,
        close=close,
        score=score,
        rsi14=float(current["rsi14"]),
        ema_spread_percent=(float(current["ema20"]) - float(current["ema50"]))
        / close
        * 100.0,
        macd_histogram_percent=float(current["macd_histogram"]) / close * 100.0,
    )


def _setup_distance(current: _Setup, candidate: _Setup) -> float:
    score_distance = abs(current.score - candidate.score) / 2.0
    rsi_distance = min(abs(current.rsi14 - candidate.rsi14) / 50.0, 1.0)
    ema_distance = min(
        abs(current.ema_spread_percent - candidate.ema_spread_percent) / 5.0,
        1.0,
    )
    macd_distance = min(
        abs(
            current.macd_histogram_percent
            - candidate.macd_histogram_percent
        )
        / 2.0,
        1.0,
    )
    return (
        score_distance * 0.45
        + rsi_distance * 0.20
        + ema_distance * 0.20
        + macd_distance * 0.15
    )


def _long_path_outcome(
    future: pd.DataFrame,
    entry: float,
    *,
    stop_loss_percent: float,
    reward_to_risk: float,
) -> _PathOutcome:
    stop = entry * (1.0 - stop_loss_percent)
    target = entry + ((entry - stop) * reward_to_risk)
    stop_distance = entry - stop
    for row in future.itertuples(index=False):
        hit_stop = float(row.low) <= stop
        hit_target = float(row.high) >= target
        if hit_stop:
            return _PathOutcome("stop", -1.0)
        if hit_target:
            return _PathOutcome("target", reward_to_risk)
    horizon_close = float(future["close"].iloc[-1])
    return _PathOutcome(
        "open",
        _clamp_r((horizon_close - entry) / stop_distance, reward_to_risk),
    )


def _short_path_outcome(
    future: pd.DataFrame,
    entry: float,
    *,
    stop_loss_percent: float,
    reward_to_risk: float,
) -> _PathOutcome:
    stop = entry * (1.0 + stop_loss_percent)
    target = entry - ((stop - entry) * reward_to_risk)
    stop_distance = stop - entry
    for row in future.itertuples(index=False):
        hit_stop = float(row.high) >= stop
        hit_target = float(row.low) <= target
        if hit_stop:
            return _PathOutcome("stop", -1.0)
        if hit_target:
            return _PathOutcome("target", reward_to_risk)
    horizon_close = float(future["close"].iloc[-1])
    return _PathOutcome(
        "open",
        _clamp_r((entry - horizon_close) / stop_distance, reward_to_risk),
    )


def _clamp_r(value: float, reward_to_risk: float) -> float:
    return max(-1.0, min(reward_to_risk, value))


def _confidence(sample_size: int) -> str:
    if sample_size >= 100:
        return "HIGH"
    if sample_size >= 50:
        return "MEDIUM"
    return "LOW"
