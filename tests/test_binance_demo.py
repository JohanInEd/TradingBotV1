from __future__ import annotations

import pytest

from btc_trading_bot.binance_demo import (
    BinanceDemoClient,
    BinanceDemoError,
    to_binance_usdm_symbol,
)
from btc_trading_bot.config import Settings


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": params or {},
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        if url.endswith("/fapi/v1/exchangeInfo"):
            return _Response(
                {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "filters": [
                                {
                                    "filterType": "LOT_SIZE",
                                    "minQty": "0.001",
                                    "stepSize": "0.001",
                                }
                            ],
                        }
                    ]
                }
            )
        if url.endswith("/fapi/v1/leverage"):
            return _Response({"leverage": 5})
        if url.endswith("/fapi/v1/order"):
            return _Response(
                {
                    "symbol": "BTCUSDT",
                    "side": self.calls[-1]["params"]["side"],
                    "orderId": 12345,
                    "clientOrderId": "abc",
                    "status": "NEW",
                }
            )
        return _Response({})


def _settings(**kwargs) -> Settings:
    return Settings(
        binance_demo_api_key="key",
        binance_demo_api_secret="secret",
        **kwargs,
    )


def test_to_binance_usdm_symbol_normalizes_ccxt_symbol() -> None:
    assert to_binance_usdm_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert to_binance_usdm_symbol("eth/usdt") == "ETHUSDT"


def test_binance_demo_client_places_signed_open_order() -> None:
    session = _Session()
    client = BinanceDemoClient(_settings(), session=session)

    order = client.open_market_position(
        symbol="BTC/USDT:USDT",
        side="LONG",
        quantity_btc=0.004806,
        leverage=5,
    )

    order_calls = [call for call in session.calls if call["url"].endswith("/fapi/v1/order")]
    assert order.order_id == "12345"
    assert order.status == "NEW"
    assert order_calls[-1]["params"]["symbol"] == "BTCUSDT"
    assert order_calls[-1]["params"]["side"] == "BUY"
    assert order_calls[-1]["params"]["quantity"] == "0.004"
    assert "signature" in order_calls[-1]["params"]
    assert order_calls[-1]["headers"]["X-MBX-APIKEY"] == "key"


def test_binance_demo_client_refuses_missing_credentials() -> None:
    with pytest.raises(BinanceDemoError):
        BinanceDemoClient(Settings())


def test_binance_demo_client_refuses_non_demo_base_url() -> None:
    with pytest.raises(BinanceDemoError):
        BinanceDemoClient(
            _settings(binance_demo_base_url="https://fapi.binance.com")
        )
