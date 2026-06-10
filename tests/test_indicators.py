from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from btc_trading_bot.indicators import analyze_multi_timeframe, analyze_technicals


def _candles(closes: list[float], hours: int = 4) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": [
                start + timedelta(hours=hours * index)
                for index in range(len(closes))
            ],
            "close": closes,
        }
    )


def test_rising_market_produces_complete_technical_analysis() -> None:
    closes = [50_000 + index * 125 for index in range(100)]

    result = analyze_technicals(_candles(closes))

    assert result.ema20 > result.ema50
    assert "Bullish" in result.ema_status
    assert result.rsi14 >= 70
    assert -1.0 <= result.score <= 1.0


def test_falling_market_has_bearish_ema_alignment() -> None:
    closes = [70_000 - index * 110 for index in range(100)]

    result = analyze_technicals(_candles(closes))

    assert result.ema20 < result.ema50
    assert "Bearish" in result.ema_status
    assert result.rsi14 <= 30


def test_multi_timeframe_analysis_combines_all_three_scores() -> None:
    rising = [50_000 + index * 125 for index in range(100)]
    falling = [70_000 - index * 110 for index in range(100)]

    result = analyze_multi_timeframe(
        _candles(rising, hours=4),
        _candles(falling, hours=24),
        _candles(rising, hours=1),
    )

    assert result.base_score is not None
    assert result.daily_trend is not None
    assert result.hourly_entry is not None
    assert result.daily_trend.score < 0
    assert result.hourly_entry.score > 0
    assert result.score == pytest.approx(
        result.base_score * 0.60
        + result.daily_trend.score * 0.25
        + result.hourly_entry.score * 0.15
    )
