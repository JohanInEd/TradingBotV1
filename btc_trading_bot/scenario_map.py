from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD

from btc_trading_bot.indicators import (
    _clamp,
    _ema_signal,
    _macd_signal,
    _rsi_signal,
)
from btc_trading_bot.models import ScenarioForecast, ScenarioPathPoint


@dataclass(frozen=True, slots=True)
class ScenarioMapSettings:
    horizon_hours: int = 168
    horizon_candles: int = 42
    lookback_candles: int = 260
    min_samples: int = 30
    max_samples: int = 100
    lower_quantile: float = 0.20
    upper_quantile: float = 0.80


@dataclass(frozen=True, slots=True)
class _ScenarioSetup:
    index: int
    close: float
    score: float
    ema_trend: int
    ema_spread_percent: float
    rsi14: float
    macd_histogram_percent: float
    atr_percent: float
    volatility_percent: float
    range_position_percent: float


def forecast_scenario_map(
    candles: pd.DataFrame,
    settings: ScenarioMapSettings | None = None,
) -> ScenarioForecast | None:
    settings = settings or ScenarioMapSettings()
    if not _valid_settings(settings):
        return None

    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        return None

    data = candles.tail(
        settings.lookback_candles + settings.horizon_candles + 80
    ).copy()
    data = data.sort_values("timestamp").reset_index(drop=True)
    for column in ("open", "high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"]).reset_index(
        drop=True
    )
    if len(data) < max(80, settings.horizon_candles + 60):
        return None

    data = _with_context_indicators(data)
    current = _setup_from_index(data, len(data) - 1)
    if current is None:
        return None

    candidates: list[tuple[float, _ScenarioSetup]] = []
    last_index = len(data) - settings.horizon_candles
    for index in range(1, last_index):
        setup = _setup_from_index(data, index)
        if setup is None:
            continue
        candidates.append((_setup_distance(current, setup), setup))

    if len(candidates) < settings.min_samples:
        return None

    candidates.sort(key=lambda item: item[0])
    selected = [
        setup for _, setup in candidates[: min(settings.max_samples, len(candidates))]
    ]
    if len(selected) < settings.min_samples:
        return None

    path_samples: list[list[float]] = []
    downside_extremes: list[float] = []
    upside_extremes: list[float] = []
    up_count = 0
    down_count = 0

    for setup in selected:
        future = data.iloc[
            setup.index + 1 : setup.index + 1 + settings.horizon_candles
        ]
        if len(future) < settings.horizon_candles or setup.close <= 0:
            continue
        path = [float(close) / setup.close - 1.0 for close in future["close"]]
        if any(not math.isfinite(value) for value in path):
            continue
        path_samples.append(path)
        final_return = path[-1]
        if final_return > 0:
            up_count += 1
        elif final_return < 0:
            down_count += 1
        downside_extremes.append(float(future["low"].min()) / setup.close - 1.0)
        upside_extremes.append(float(future["high"].max()) / setup.close - 1.0)

    sample_size = len(path_samples)
    if sample_size < settings.min_samples:
        return None

    current_time = _timestamp(data.iloc[-1]["timestamp"])
    current_price = current.close
    median_changes = _path_quantiles(path_samples, 0.50)
    lower_changes = _path_quantiles(path_samples, settings.lower_quantile)
    upper_changes = _path_quantiles(path_samples, settings.upper_quantile)
    downside = _quantile(downside_extremes, settings.lower_quantile)
    upside = _quantile(upside_extremes, settings.upper_quantile)

    return ScenarioForecast(
        horizon_hours=settings.horizon_hours,
        sample_size=sample_size,
        candidate_count=len(candidates),
        confidence=_confidence(sample_size),
        method=(
            "Historical scenario from nearest closed 4h technical setups; "
            "percent-change paths remapped to current BTC price. Scenario "
            "analysis only, not a prediction."
        ),
        generated_at=datetime.now(timezone.utc),
        up_probability=up_count / sample_size,
        down_probability=down_count / sample_size,
        median_path=_build_path_points(
            current_time,
            current_price,
            median_changes,
            candle_hours=settings.horizon_hours / settings.horizon_candles,
        ),
        lower_band_path=_build_path_points(
            current_time,
            current_price,
            lower_changes,
            candle_hours=settings.horizon_hours / settings.horizon_candles,
        ),
        upper_band_path=_build_path_points(
            current_time,
            current_price,
            upper_changes,
            candle_hours=settings.horizon_hours / settings.horizon_candles,
        ),
        expected_low=min(current_price, current_price * (1.0 + downside)),
        expected_high=max(current_price, current_price * (1.0 + upside)),
    )


def _valid_settings(settings: ScenarioMapSettings) -> bool:
    return (
        settings.horizon_hours > 0
        and settings.horizon_candles > 0
        and settings.lookback_candles > settings.horizon_candles
        and settings.min_samples > 0
        and settings.max_samples >= settings.min_samples
        and 0.0 <= settings.lower_quantile <= 0.5
        and 0.5 <= settings.upper_quantile <= 1.0
    )


def _with_context_indicators(data: pd.DataFrame) -> pd.DataFrame:
    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    previous_close = close.shift(1)

    data = data.copy()
    data["ema20"] = EMAIndicator(close=close, window=20).ema_indicator()
    data["ema50"] = EMAIndicator(close=close, window=50).ema_indicator()
    data["rsi14"] = RSIIndicator(close=close, window=14).rsi()
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    data["macd"] = macd.macd()
    data["macd_signal"] = macd.macd_signal()
    data["macd_histogram"] = macd.macd_diff()

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14).mean()
    realized_volatility = close.pct_change().rolling(20).std() * math.sqrt(6) * 100
    rolling_high = high.rolling(50).max()
    rolling_low = low.rolling(50).min()
    range_span = rolling_high - rolling_low

    data["atr_percent"] = atr / close * 100.0
    data["volatility_percent"] = pd.concat(
        [data["atr_percent"], realized_volatility], axis=1
    ).max(axis=1)
    data["range_position_percent"] = (
        (close - rolling_low) / range_span.replace(0, pd.NA) * 100.0
    ).fillna(50.0)
    return data


def _setup_from_index(data: pd.DataFrame, index: int) -> _ScenarioSetup | None:
    if index <= 0:
        return None

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
        current["atr_percent"],
        current["volatility_percent"],
        current["range_position_percent"],
        previous["ema20"],
        previous["ema50"],
        previous["macd"],
        previous["macd_signal"],
        previous["macd_histogram"],
    )
    if any(not _is_finite(value) for value in values):
        return None

    close = float(current["close"])
    if close <= 0:
        return None

    _, ema_score = _ema_signal(current, previous)
    _, rsi_score = _rsi_signal(float(current["rsi14"]))
    _, macd_score = _macd_signal(current, previous)
    score = _clamp(0.40 * ema_score + 0.25 * rsi_score + 0.35 * macd_score)

    return _ScenarioSetup(
        index=index,
        close=close,
        score=score,
        ema_trend=1 if float(current["ema20"]) >= float(current["ema50"]) else -1,
        ema_spread_percent=(
            (float(current["ema20"]) - float(current["ema50"])) / close * 100.0
        ),
        rsi14=float(current["rsi14"]),
        macd_histogram_percent=float(current["macd_histogram"]) / close * 100.0,
        atr_percent=float(current["atr_percent"]),
        volatility_percent=float(current["volatility_percent"]),
        range_position_percent=max(
            0.0, min(100.0, float(current["range_position_percent"]))
        ),
    )


def _setup_distance(current: _ScenarioSetup, candidate: _ScenarioSetup) -> float:
    score_distance = abs(current.score - candidate.score) / 2.0
    ema_trend_distance = 0.0 if current.ema_trend == candidate.ema_trend else 1.0
    ema_spread_distance = min(
        abs(current.ema_spread_percent - candidate.ema_spread_percent) / 5.0,
        1.0,
    )
    rsi_distance = min(abs(current.rsi14 - candidate.rsi14) / 50.0, 1.0)
    macd_distance = min(
        abs(
            current.macd_histogram_percent
            - candidate.macd_histogram_percent
        )
        / 2.0,
        1.0,
    )
    atr_distance = min(abs(current.atr_percent - candidate.atr_percent) / 3.0, 1.0)
    volatility_distance = min(
        abs(current.volatility_percent - candidate.volatility_percent) / 4.0,
        1.0,
    )
    range_distance = min(
        abs(current.range_position_percent - candidate.range_position_percent)
        / 100.0,
        1.0,
    )
    return (
        score_distance * 0.26
        + ema_trend_distance * 0.10
        + ema_spread_distance * 0.14
        + rsi_distance * 0.16
        + macd_distance * 0.12
        + atr_distance * 0.10
        + volatility_distance * 0.06
        + range_distance * 0.06
    )


def _path_quantiles(paths: list[list[float]], quantile: float) -> list[float]:
    return [
        _quantile([path[index] for path in paths], quantile)
        for index in range(len(paths[0]))
    ]


def _quantile(values: list[float], quantile: float) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return 0.0
    return float(pd.Series(finite).quantile(quantile))


def _build_path_points(
    current_time: datetime,
    current_price: float,
    changes: list[float],
    *,
    candle_hours: float,
) -> tuple[ScenarioPathPoint, ...]:
    return tuple(
        ScenarioPathPoint(
            time=current_time + timedelta(hours=candle_hours * (index + 1)),
            price=current_price * (1.0 + change),
            percent_change=change * 100.0,
        )
        for index, change in enumerate(changes)
    )


def _timestamp(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return pd.to_datetime(value).to_pydatetime()


def _is_finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _confidence(sample_size: int) -> str:
    if sample_size >= 100:
        return "HIGH"
    if sample_size >= 50:
        return "MEDIUM"
    return "LOW"
