from btc_trading_bot.config import Settings
from btc_trading_bot.meta_model import (
    assess_meta_model,
    predict_tp_probability,
    train_meta_model,
)


def _row(outcome: str, technical_score: float, atr: float, side: str = "LONG") -> dict:
    return {
        "outcome": outcome,
        "side": side,
        "technical_score": technical_score,
        "reward_to_risk": 2.0,
        "market_context": {
            "atr_percent": atr,
            "range_position_percent": 50.0,
            "trend_strength_percent": 2.0,
        },
        "probability_forecast": {
            "expected_long_r": 0.4 if outcome == "TP" else -0.2,
            "expected_short_r": 0.0,
        },
    }


def _separable_rows(count: int = 60) -> list[dict]:
    rows = []
    for index in range(count):
        if index % 2 == 0:
            rows.append(_row("TP", technical_score=0.8, atr=1.0))
        else:
            rows.append(_row("SL", technical_score=-0.1, atr=4.0))
    return rows


def test_training_requires_enough_two_class_samples() -> None:
    assert train_meta_model([], min_samples=10) is None
    assert train_meta_model(_separable_rows(8), min_samples=10) is None
    single_class = [_row("TP", 0.8, 1.0) for _ in range(50)]
    assert train_meta_model(single_class, min_samples=10) is None


def test_model_learns_separable_outcomes() -> None:
    model = train_meta_model(_separable_rows(), min_samples=40)

    assert model is not None
    assert model.sample_count == 60
    assert model.train_accuracy >= 0.9

    winner_features = [1.0, 0.8, 1.0, 50.0, 2.0, 2.0, 0.4]
    loser_features = [1.0, -0.1, 4.0, 50.0, 2.0, 2.0, -0.2]
    assert predict_tp_probability(model, winner_features) > 0.6
    assert predict_tp_probability(model, loser_features) < 0.4
    # Missing values fall back to feature means without crashing.
    partial = predict_tp_probability(model, [1.0, 0.8, None, None, None, 2.0, None])
    assert 0.0 <= partial <= 1.0


def test_assessment_states_and_gate() -> None:
    settings = Settings(meta_min_tp_probability=0.45)
    untrained = assess_meta_model(None, settings=settings, side="LONG")
    assert untrained.status == "UNTRAINED"
    assert not untrained.trained

    disabled = assess_meta_model(
        None, settings=Settings(meta_model_enabled=False), side="LONG"
    )
    assert disabled.status == "DISABLED"

    model = train_meta_model(_separable_rows(), min_samples=40)
    assert model is not None

    from datetime import datetime, timezone

    from btc_trading_bot.models import MarketContext, TechnicalAnalysis

    def technical(score: float) -> TechnicalAnalysis:
        return TechnicalAnalysis(
            candle_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
            close=100.0,
            ema20=101.0,
            ema50=99.0,
            ema_status="Bullish alignment",
            rsi14=60.0,
            rsi_status="Bullish momentum",
            macd=2.0,
            macd_signal=1.0,
            macd_histogram=1.0,
            macd_status="Bullish, strengthening",
            score=score,
        )

    def context(atr: float) -> MarketContext:
        return MarketContext(
            volatility_regime="NORMAL VOLATILITY",
            structure_regime="TRENDING UP",
            atr_percent=atr,
            realized_volatility_percent=1.0,
            bollinger_width_percent=5.0,
            range_position_percent=50.0,
            trend_strength_percent=2.0,
            reason="test",
            updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

    strong = assess_meta_model(
        model,
        settings=settings,
        side="LONG",
        technical=technical(0.8),
        market_context=context(1.0),
    )
    assert strong.status == "PASS"
    assert strong.tp_probability is not None and strong.tp_probability > 0.45

    weak = assess_meta_model(
        model,
        settings=settings,
        side="LONG",
        technical=technical(-0.1),
        market_context=context(4.0),
    )
    assert weak.status == "BLOCKED"
    assert weak.tp_probability is not None and weak.tp_probability < 0.45
