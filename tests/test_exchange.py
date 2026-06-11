from datetime import datetime, timedelta, timezone

import pandas as pd

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import (
    ExchangeClient,
    market_snapshot_from_ticker,
    merge_candle_update,
    resolve_exchange_spec,
)


class _FakeExchange:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows
        self.requested_timeframe: str | None = None

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int
    ) -> list[list[float]]:
        self.requested_timeframe = timeframe
        return self.rows

    def parse_timeframe(self, timeframe: str) -> int:
        return {"1h": 3600, "4h": 14_400, "1d": 86_400}[timeframe]


def test_fetch_closed_candles_uses_requested_timeframe_boundary() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(hours=62)
    rows = [
        [
            int((start + timedelta(hours=index)).timestamp() * 1000),
            100.0,
            101.0,
            99.0,
            100.0 + index,
            1.0,
        ]
        for index in range(63)
    ]
    exchange = _FakeExchange(rows)
    client = ExchangeClient.__new__(ExchangeClient)
    client.settings = Settings()
    client.exchange = exchange

    candles = client.fetch_closed_candles("1h")

    assert exchange.requested_timeframe == "1h"
    assert len(candles) == 62
    assert candles.iloc[-1]["timestamp"].to_pydatetime() == now - timedelta(hours=1)


def test_websocket_ticker_includes_bid_ask_and_calculated_change() -> None:
    snapshot = market_snapshot_from_ticker(
        {
            "last": 105.0,
            "open": 100.0,
            "bid": 104.5,
            "ask": 105.5,
        },
        exchange="Test Exchange",
        symbol="BTC/USDT",
        source="WebSocket",
    )

    assert snapshot.price == 105.0
    assert snapshot.change_24h == 5.0
    assert snapshot.bid == 104.5
    assert snapshot.ask == 105.5
    assert snapshot.source == "WebSocket"


def test_live_candle_replaces_current_row_then_appends_next_row() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = pd.DataFrame(
        [
            {
                "timestamp": start,
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 1.0,
            }
        ]
    )
    current_timestamp = int(start.timestamp() * 1000)

    replaced = merge_candle_update(
        candles,
        [current_timestamp, 100.0, 106.0, 98.0, 104.0, 2.0],
        limit=10,
    )
    appended = merge_candle_update(
        replaced,
        [
            int((start + timedelta(hours=1)).timestamp() * 1000),
            104.0,
            108.0,
            103.0,
            107.0,
            3.0,
        ],
        limit=10,
    )

    assert len(replaced) == 1
    assert replaced.iloc[-1]["close"] == 104.0
    assert len(appended) == 2
    assert appended.iloc[-1]["close"] == 107.0


def test_binance_usdm_uses_linear_perpetual_market() -> None:
    spec = resolve_exchange_spec("binance-usdm", "BTC/USDT")

    assert spec.ccxt_id == "binanceusdm"
    assert spec.symbol == "BTC/USDT:USDT"
    assert spec.options == {"defaultType": "future"}


def test_binance_usdm_preserves_explicit_settlement_symbol() -> None:
    spec = resolve_exchange_spec("binance-usdm", "ETH/USDT:USDT")

    assert spec.symbol == "ETH/USDT:USDT"


def test_exchange_name_is_safe_for_legacy_windows_console() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.exchange = type(
        "Exchange",
        (),
        {"name": "Binance USD\u24c8-M"},
    )()

    assert client.name == "Binance USD-M"
