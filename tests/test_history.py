import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from btc_trading_bot.history import (
    HistoryAnalysisSettings,
    HistoryStore,
    analyze_history_store,
    compute_feature_outcomes,
    format_history_report,
    sync_timeframe,
)


def _candles(
    count: int,
    *,
    start: datetime | None = None,
    hours: int = 4,
    step: float = 1.0,
) -> list[dict]:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(count):
        open_price = price
        close = price + step
        high = max(open_price, close) + abs(step) * 2.0
        low = min(open_price, close) - abs(step) * 0.2
        rows.append(
            {
                "timestamp": start + timedelta(hours=hours * index),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10.0 + index,
            }
        )
        price = close
    return rows


def test_history_store_creates_sqlite_schema(tmp_path) -> None:
    path = tmp_path / "history.sqlite"

    with HistoryStore(path):
        pass

    with sqlite3.connect(path) as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }

    assert "candles" in names
    assert "idx_candles_lookup_timestamp" in names
    assert "idx_candles_timestamp" in names


def test_history_store_upserts_and_deduplicates_candles(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with HistoryStore(tmp_path / "history.sqlite") as store:
        store.upsert_candles(
            "binanceusdm",
            "BTC/USDT:USDT",
            "4h",
            [
                [int(start.timestamp() * 1000), 100.0, 101.0, 99.0, 100.0, 1.0],
                [int(start.timestamp() * 1000), 100.0, 102.0, 98.0, 101.0, 2.0],
            ],
        )
        store.upsert_candles(
            "binanceusdm",
            "BTC/USDT:USDT",
            "4h",
            [
                [int(start.timestamp() * 1000), 101.0, 103.0, 100.0, 102.0, 3.0],
            ],
        )

        candles = store.load_candles("binanceusdm", "BTC/USDT:USDT", "4h")

    assert len(candles) == 1
    assert candles.iloc[0]["close"] == 102.0
    assert candles.iloc[0]["volume"] == 3.0


def test_history_store_reports_missing_candle_windows(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with HistoryStore(tmp_path / "history.sqlite") as store:
        store.upsert_candles(
            "binanceusdm",
            "BTC/USDT:USDT",
            "4h",
            [_candles(1, start=start)[0], _candles(1, start=start + timedelta(hours=8))[0]],
        )

        windows = store.missing_candle_windows(
            "binanceusdm",
            "BTC/USDT:USDT",
            "4h",
            start=start,
            end=start + timedelta(hours=12),
        )

    assert windows == [
        (start + timedelta(hours=4), start + timedelta(hours=4)),
        (start + timedelta(hours=12), start + timedelta(hours=12)),
    ]


def test_history_sync_fetches_incrementally_after_latest_candle(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timeframe_ms = 4 * 60 * 60 * 1000

    class FakeExchange:
        def __init__(self) -> None:
            self.calls: list[int | None] = []

        def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
            self.calls.append(since)
            return [
                [since, 101.0, 103.0, 100.0, 102.0, 1.0],
                [since + timeframe_ms, 102.0, 104.0, 101.0, 103.0, 1.0],
            ]

    exchange = FakeExchange()
    with HistoryStore(tmp_path / "history.sqlite") as store:
        store.upsert_candles("binanceusdm", "BTC/USDT:USDT", "4h", _candles(1, start=start))

        result = sync_timeframe(
            store,
            exchange,
            exchange="binanceusdm",
            symbol="BTC/USDT:USDT",
            timeframe="4h",
            until=start + timedelta(hours=12),
        )

        assert exchange.calls == [int((start + timedelta(hours=4)).timestamp() * 1000)]
        assert result.stored_count == 2
        assert store.count_candles("binanceusdm", "BTC/USDT:USDT", "4h") == 3


def test_feature_outcomes_include_indicators_and_tp_sl_results() -> None:
    data = compute_feature_outcomes(
        _candles(90, step=1.0),
        "4h",
        HistoryAnalysisSettings(stop_loss_percent=0.005, reward_to_risk=1.0),
    )
    completed = data[data["movement_24h_percent"].notna() & data["score"].notna()]
    sample = completed.iloc[0]

    assert sample["ema20"] > sample["ema50"]
    assert sample["rsi14"] > 50
    assert sample["macd_histogram"] == pytest.approx(sample["macd"] - sample["macd_signal"])
    assert sample["atr_percent"] > 0
    assert sample["bollinger_width_percent"] > 0
    assert sample["realized_volatility_percent"] >= 0
    assert sample["range_position_percent"] > 50
    assert sample["trend_spread_percent"] > 0
    assert sample["movement_24h_percent"] > 0
    assert sample["long_tp_sl_outcome"] == "TP"
    assert sample["short_tp_sl_outcome"] == "SL"
    assert sample["expected_r"] == pytest.approx(1.0)


def test_history_analyzer_reports_grouped_summary(tmp_path) -> None:
    with HistoryStore(tmp_path / "history.sqlite") as store:
        store.upsert_candles(
            "binanceusdm",
            "BTC/USDT:USDT",
            "4h",
            _candles(100, step=1.0),
        )

        report = analyze_history_store(
            store,
            exchange="binanceusdm",
            symbol="BTC/USDT:USDT",
            timeframes=("4h",),
            settings=HistoryAnalysisSettings(
                stop_loss_percent=0.005,
                reward_to_risk=1.0,
                row_limit=200,
            ),
        )

    output = format_history_report(report)

    assert report.row_count == 100
    assert report.sample_count > 0
    assert report.groups["timeframe"]["4h"].sample_count == report.sample_count
    assert "Completed outcome samples:" in output
    assert "By timeframe:" in output
    assert "expectedR=" in output
