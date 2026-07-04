from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import urlencode

import requests

from btc_trading_bot.config import Settings


class BinanceDemoError(RuntimeError):
    """Raised when Binance Demo order execution cannot be completed."""


@dataclass(frozen=True, slots=True)
class BinanceDemoOrder:
    symbol: str
    side: str
    order_id: str
    client_order_id: str | None
    status: str
    raw: dict[str, Any]


class BinanceDemoClient:
    """Small signed REST client for Binance USD-M Demo Trading.

    It intentionally targets only the demo base URL and only the active
    trader's market open/close flow.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = settings.binance_demo_api_key
        self.api_secret = settings.binance_demo_api_secret
        self.base_url = settings.binance_demo_base_url.rstrip("/")
        self.recv_window_ms = settings.binance_demo_recv_window_ms
        self.session = session or requests.Session()
        self._symbol_rules: dict[str, dict[str, Any]] = {}
        if not self.api_key or not self.api_secret:
            raise BinanceDemoError(
                "BOT_BINANCE_DEMO_API_KEY and BOT_BINANCE_DEMO_API_SECRET are required"
            )
        if "demo-fapi.binance.com" not in self.base_url:
            raise BinanceDemoError(
                "Refusing to send active-trader demo orders outside demo-fapi.binance.com"
            )

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v3/account", signed=True)

    def open_market_position(
        self,
        *,
        symbol: str,
        side: str,
        quantity_btc: float,
        leverage: int,
    ) -> BinanceDemoOrder:
        market_symbol = to_binance_usdm_symbol(symbol)
        quantity = self._format_quantity(market_symbol, quantity_btc)
        self._set_leverage(market_symbol, leverage)
        response = self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": market_symbol,
                "side": "BUY" if side == "LONG" else "SELL",
                "type": "MARKET",
                "quantity": quantity,
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        return _order_from_response(response, fallback_symbol=market_symbol)

    def close_market_position(
        self,
        *,
        symbol: str,
        side: str,
        quantity_btc: float,
    ) -> BinanceDemoOrder:
        market_symbol = to_binance_usdm_symbol(symbol)
        quantity = self._format_quantity(market_symbol, quantity_btc)
        response = self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": market_symbol,
                "side": "SELL" if side == "LONG" else "BUY",
                "type": "MARKET",
                "quantity": quantity,
                "reduceOnly": "true",
                "newOrderRespType": "RESULT",
            },
            signed=True,
        )
        return _order_from_response(response, fallback_symbol=market_symbol)

    def _set_leverage(self, symbol: str, leverage: int) -> None:
        self._request(
            "POST",
            "/fapi/v1/leverage",
            {
                "symbol": symbol,
                "leverage": max(1, min(125, int(leverage or 1))),
            },
            signed=True,
        )

    def _format_quantity(self, symbol: str, quantity: float) -> str:
        if quantity <= 0:
            raise BinanceDemoError("Order quantity must be positive")
        rules = self._symbol_rule(symbol)
        step = Decimal(str(rules.get("step_size") or "0.001"))
        min_qty = Decimal(str(rules.get("min_qty") or "0"))
        value = Decimal(str(quantity)).quantize(step, rounding=ROUND_DOWN)
        if value < min_qty:
            raise BinanceDemoError(
                f"Quantity {quantity:.8f} {symbol} is below demo minimum {min_qty}"
            )
        return format(value.normalize(), "f")

    def _symbol_rule(self, symbol: str) -> dict[str, Any]:
        cached = self._symbol_rules.get(symbol)
        if cached is not None:
            return cached
        info = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        for row in info.get("symbols", []):
            if row.get("symbol") != symbol:
                continue
            rule: dict[str, Any] = {"step_size": None, "min_qty": None}
            for filter_row in row.get("filters", []):
                if filter_row.get("filterType") == "LOT_SIZE":
                    rule["step_size"] = filter_row.get("stepSize")
                    rule["min_qty"] = filter_row.get("minQty")
            self._symbol_rules[symbol] = rule
            return rule
        raise BinanceDemoError(f"{symbol} was not found in Binance Demo exchangeInfo")

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool,
    ) -> dict[str, Any]:
        request_params = {
            key: value
            for key, value in (params or {}).items()
            if value is not None and value != ""
        }
        headers: dict[str, str] = {}
        if signed:
            request_params["timestamp"] = int(time.time() * 1000)
            request_params["recvWindow"] = self.recv_window_ms
            query = urlencode(request_params)
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            request_params["signature"] = signature
            headers["X-MBX-APIKEY"] = self.api_key

        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                params=request_params,
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            raise BinanceDemoError(f"Binance Demo request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BinanceDemoError(
                f"Binance Demo returned non-JSON response HTTP {response.status_code}"
            ) from exc
        if response.status_code >= 400:
            message = payload.get("msg") if isinstance(payload, dict) else payload
            raise BinanceDemoError(
                f"Binance Demo HTTP {response.status_code}: {message}"
            )
        if not isinstance(payload, dict):
            raise BinanceDemoError("Binance Demo returned an unexpected payload")
        return payload


def to_binance_usdm_symbol(symbol: str) -> str:
    base = symbol.split(":", maxsplit=1)[0]
    return base.replace("/", "").upper()


def _order_from_response(
    response: dict[str, Any],
    *,
    fallback_symbol: str,
) -> BinanceDemoOrder:
    return BinanceDemoOrder(
        symbol=str(response.get("symbol") or fallback_symbol),
        side=str(response.get("side") or ""),
        order_id=str(response.get("orderId") or ""),
        client_order_id=(
            str(response.get("clientOrderId"))
            if response.get("clientOrderId") is not None
            else None
        ),
        status=str(response.get("status") or ""),
        raw=response,
    )
