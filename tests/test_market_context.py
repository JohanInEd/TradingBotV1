from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.market_context import analyze_market_context


def _candles(
    closes: list[float], hours: int = 4, wick_percent: float = 0.004
) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(hours=hours * index)
                for index in range(len(closes))
            ],
            "high": [close * (1 + wick_percent) for close in closes],
            "low": [close * (1 - wick_percent) for close in closes],
            "close": closes,
        }
    )


def test_market_context_identifies_trending_up_market() -> None:
    closes = [50_000 + index * 150 for index in range(100)]

    context = analyze_market_context(_candles(closes))

    assert context.structure_regime == "TRENDING UP"
    assert context.atr_percent > 0
    assert context.range_position_percent > 70
    assert "atr" in context.reason.lower()


def test_market_context_handles_compressed_sideways_market() -> None:
    closes = [60_000 + (index % 3 - 1) * 20 for index in range(100)]

    context = analyze_market_context(_candles(closes, wick_percent=0.0005))

    assert context.volatility_regime == "COMPRESSED VOLATILITY"
    assert context.bollinger_width_percent < 3.0
    assert 0 <= context.range_position_percent <= 100
