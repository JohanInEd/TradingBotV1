from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from btc_trading_bot.config import Settings
from btc_trading_bot.exchange import (
    ExchangeClient,
    MarketDataError,
    futures_metrics_from_responses,
    market_snapshot_from_ticker,
    merge_candle_update,
    resolve_exchange_spec,
)
from btc_trading_bot.realtime import _binance_stream_symbol


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


def test_binance_stream_symbol_removes_slash_and_settlement() -> None:
    assert _binance_stream_symbol("BTC/USDT:USDT") == "btcusdt"


def test_exchange_name_is_safe_for_legacy_windows_console() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.exchange = type(
        "Exchange",
        (),
        {"name": "Binance USD\u24c8-M"},
    )()

    assert client.name == "Binance USD-M"


def test_connect_failure_tolerates_exchange_without_close(monkeypatch) -> None:
    class BrokenExchange:
        name = "Broken"
        markets = {}
        has = {}

        def __init__(self, config):
            self.id = "broken"

        def load_markets(self):
            raise RuntimeError("network blocked")

    import btc_trading_bot.exchange as exchange_module

    monkeypatch.setattr(exchange_module.ccxt, "broken", BrokenExchange, raising=False)

    with pytest.raises(MarketDataError, match="network blocked"):
        ExchangeClient(Settings(exchange="broken", max_retries=1))


def test_futures_metrics_normalize_public_binance_responses() -> None:
    updated_at = datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc)

    metrics = futures_metrics_from_responses(
        {
            "markPrice": 63_500.0,
            "indexPrice": 63_550.0,
            "fundingRate": 0.0001,
            "fundingTimestamp": int(
                datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc).timestamp()
                * 1000
            ),
        },
        {
            "openInterestAmount": 100_000.0,
            "openInterestValue": None,
        },
        [{"longShortRatio": 1.65}],
        [{"longShortRatio": 1.80}],
        [{"longShortRatio": 2.10}],
        [{"buySellRatio": 1.25, "buyVol": 12_000.0, "sellVol": 9_600.0}],
        updated_at=updated_at,
    )

    assert metrics.mark_price == 63_500.0
    assert metrics.index_price == 63_550.0
    assert metrics.funding_rate == 0.0001
    assert metrics.open_interest_value == 6_350_000_000.0
    assert metrics.long_short_ratio == 1.65
    assert metrics.top_trader_long_short_ratio == 1.80
    assert metrics.top_trader_position_ratio == 2.10
    assert metrics.taker_buy_sell_ratio == 1.25
    assert metrics.taker_buy_volume == 12_000.0
    assert metrics.crowding_score is not None
    assert metrics.crowding_label in {"Long-Leaning", "Crowded Long"}
    assert metrics.next_funding_at == datetime(
        2026, 6, 11, 16, 0, tzinfo=timezone.utc
    )


class _FakeDerivativesExchange:
    id = "binanceusdm"

    def fetch_funding_rate(self, symbol: str) -> dict[str, float]:
        return {
            "markPrice": 100.0,
            "indexPrice": 99.5,
            "fundingRate": 0.0002,
        }

    def fetch_open_interest(self, symbol: str) -> dict[str, float]:
        return {"openInterestAmount": 25.0}

    def fetch_long_short_ratio_history(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[dict[str, float]]:
        return [{"longShortRatio": 1.2}]

    def market(self, symbol: str) -> dict[str, str]:
        return {"id": "BTCUSDT"}

    def fapiDataGetTopLongShortAccountRatio(
        self, params: dict[str, object]
    ) -> list[dict[str, float]]:
        return [{"longShortRatio": 1.4}]

    def fapiDataGetTopLongShortPositionRatio(
        self, params: dict[str, object]
    ) -> list[dict[str, float]]:
        return [{"longShortRatio": 1.5}]

    def fapiDataGetTakerlongshortRatio(
        self, params: dict[str, object]
    ) -> list[dict[str, float]]:
        return [{"buySellRatio": 1.1, "buyVol": 1000.0, "sellVol": 900.0}]


def test_fetch_futures_metrics_uses_unified_ccxt_methods() -> None:
    client = ExchangeClient.__new__(ExchangeClient)
    client.settings = Settings()
    client.spec = resolve_exchange_spec("binance-usdm", "BTC/USDT")
    client.exchange = _FakeDerivativesExchange()

    metrics, errors = client.fetch_futures_metrics()

    assert errors == ()
    assert metrics is not None
    assert metrics.mark_price == 100.0
    assert metrics.open_interest_amount == 25.0
    assert metrics.long_short_ratio == 1.2
    assert metrics.top_trader_long_short_ratio == 1.4
    assert metrics.top_trader_position_ratio == 1.5
    assert metrics.taker_buy_sell_ratio == 1.1
