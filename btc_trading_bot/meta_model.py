from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    MarketContext,
    MetaModelAssessment,
    ProbabilityForecast,
    TechnicalAnalysis,
)
from btc_trading_bot.paper_setups import OUTCOME_SL, OUTCOME_TP

LOGGER = logging.getLogger(__name__)
FEATURE_NAMES = (
    "side_long",
    "technical_score",
    "atr_percent",
    "range_position_percent",
    "trend_strength_percent",
    "reward_to_risk",
    "expected_r",
)
_TRAIN_ITERATIONS = 500
_LEARNING_RATE = 0.1
_L2_LAMBDA = 0.01


@dataclass(frozen=True, slots=True)
class MetaModel:
    """Logistic regression over resolved paper-setup outcomes.

    Secondary meta-labeling model: the rule engine picks direction, this model
    estimates the probability that a setup with these features reaches TP
    before SL, based on the journal's own recorded history.
    """

    weights: tuple[float, ...]
    bias: float
    feature_means: tuple[float, ...]
    feature_stds: tuple[float, ...]
    sample_count: int
    positive_count: int
    train_accuracy: float
    trained_at: datetime


def train_meta_model(
    rows: list[dict[str, Any]],
    *,
    min_samples: int = 40,
) -> MetaModel | None:
    samples: list[list[float | None]] = []
    labels: list[float] = []
    for row in rows:
        outcome = row.get("outcome")
        if outcome not in {OUTCOME_TP, OUTCOME_SL}:
            continue
        samples.append(_features_from_row(row))
        labels.append(1.0 if outcome == OUTCOME_TP else 0.0)

    if len(samples) < min_samples:
        return None
    positives = int(sum(labels))
    if positives == 0 or positives == len(labels):
        # A single-class history cannot be fit meaningfully.
        return None

    matrix = _impute(np.array(
        [[np.nan if value is None else value for value in sample] for sample in samples],
        dtype=float,
    ))
    means = matrix.mean(axis=0)
    stds = matrix.std(axis=0)
    stds[stds == 0] = 1.0
    standardized = (matrix - means) / stds
    targets = np.array(labels, dtype=float)

    weights = np.zeros(standardized.shape[1])
    bias = 0.0
    count = float(len(targets))
    for _ in range(_TRAIN_ITERATIONS):
        logits = standardized @ weights + bias
        predictions = _sigmoid(logits)
        error = predictions - targets
        gradient = (standardized.T @ error) / count + _L2_LAMBDA * weights
        bias_gradient = float(error.mean())
        weights -= _LEARNING_RATE * gradient
        bias -= _LEARNING_RATE * bias_gradient

    fitted = _sigmoid(standardized @ weights + bias)
    accuracy = float(((fitted >= 0.5) == (targets >= 0.5)).mean())
    return MetaModel(
        weights=tuple(float(value) for value in weights),
        bias=float(bias),
        feature_means=tuple(float(value) for value in means),
        feature_stds=tuple(float(value) for value in stds),
        sample_count=len(labels),
        positive_count=positives,
        train_accuracy=accuracy,
        trained_at=datetime.now(timezone.utc),
    )


def predict_tp_probability(
    model: MetaModel,
    features: list[float | None],
) -> float:
    values = np.array(
        [
            model.feature_means[index] if value is None else float(value)
            for index, value in enumerate(features)
        ],
        dtype=float,
    )
    standardized = (values - np.array(model.feature_means)) / np.array(
        model.feature_stds
    )
    return float(_sigmoid(standardized @ np.array(model.weights) + model.bias))


def assess_meta_model(
    model: MetaModel | None,
    *,
    settings: Settings,
    side: str,
    technical: TechnicalAnalysis | None = None,
    market_context: MarketContext | None = None,
    probability_forecast: ProbabilityForecast | None = None,
) -> MetaModelAssessment:
    threshold = settings.meta_min_tp_probability
    if not settings.meta_model_enabled:
        return MetaModelAssessment(
            status="DISABLED",
            trained=model is not None,
            sample_count=model.sample_count if model is not None else 0,
            tp_probability=None,
            threshold=threshold,
            detail="Meta model gate is disabled.",
        )
    if model is None:
        return MetaModelAssessment(
            status="UNTRAINED",
            trained=False,
            sample_count=0,
            tp_probability=None,
            threshold=threshold,
            detail=(
                "Not enough resolved TP/SL paper setups to train the meta "
                f"model (need {settings.meta_min_training_samples})."
            ),
        )

    tp_probability = predict_tp_probability(
        model,
        _features_from_current(
            side=side,
            technical=technical,
            market_context=market_context,
            probability_forecast=probability_forecast,
            reward_to_risk=settings.reward_to_risk,
        ),
    )
    if tp_probability < threshold:
        return MetaModelAssessment(
            status="BLOCKED",
            trained=True,
            sample_count=model.sample_count,
            tp_probability=tp_probability,
            threshold=threshold,
            detail=(
                f"Meta model estimates {tp_probability:.0%} TP odds for this "
                f"{side} setup, below the {threshold:.0%} floor "
                f"(trained on {model.sample_count} resolved setups)."
            ),
        )
    return MetaModelAssessment(
        status="PASS",
        trained=True,
        sample_count=model.sample_count,
        tp_probability=tp_probability,
        threshold=threshold,
        detail=(
            f"Meta model estimates {tp_probability:.0%} TP odds "
            f"(trained on {model.sample_count} resolved setups, "
            f"{model.train_accuracy:.0%} in-sample accuracy)."
        ),
    )


def _features_from_row(row: dict[str, Any]) -> list[float | None]:
    side = str(row.get("side") or "")
    context = row.get("market_context")
    context = context if isinstance(context, dict) else {}
    probability = row.get("probability_forecast")
    probability = probability if isinstance(probability, dict) else {}
    expected_r = (
        probability.get("expected_long_r")
        if side == "LONG"
        else probability.get("expected_short_r")
    )
    return [
        1.0 if side == "LONG" else 0.0,
        _finite_or_none(row.get("technical_score")),
        _finite_or_none(context.get("atr_percent")),
        _finite_or_none(context.get("range_position_percent")),
        _finite_or_none(context.get("trend_strength_percent")),
        _finite_or_none(row.get("reward_to_risk")),
        _finite_or_none(expected_r),
    ]


def _features_from_current(
    *,
    side: str,
    technical: TechnicalAnalysis | None,
    market_context: MarketContext | None,
    probability_forecast: ProbabilityForecast | None,
    reward_to_risk: float,
) -> list[float | None]:
    expected_r = None
    if probability_forecast is not None:
        expected_r = (
            probability_forecast.expected_long_r
            if side == "LONG"
            else probability_forecast.expected_short_r
        )
    return [
        1.0 if side == "LONG" else 0.0,
        technical.score if technical is not None else None,
        market_context.atr_percent if market_context is not None else None,
        (
            market_context.range_position_percent
            if market_context is not None
            else None
        ),
        (
            market_context.trend_strength_percent
            if market_context is not None
            else None
        ),
        reward_to_risk,
        expected_r,
    ]


def _impute(matrix: np.ndarray) -> np.ndarray:
    for column in range(matrix.shape[1]):
        values = matrix[:, column]
        finite = values[np.isfinite(values)]
        fill = float(finite.mean()) if finite.size else 0.0
        values[~np.isfinite(values)] = fill
    return matrix


def _sigmoid(values: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -35.0, 35.0)))


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
