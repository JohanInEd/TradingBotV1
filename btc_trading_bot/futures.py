from __future__ import annotations

from btc_trading_bot.config import Settings
from btc_trading_bot.models import (
    FuturesRecommendation,
    MarketSnapshot,
    SignalResult,
)


def build_futures_recommendation(
    signal: SignalResult,
    market: MarketSnapshot,
    settings: Settings,
) -> FuturesRecommendation:
    if signal.signal == "STRONG BUY":
        side = "LONG"
        action = "GO LONG"
        entry = market.ask or market.price
        stop = entry * (1.0 - settings.stop_loss_percent)
        target = entry + ((entry - stop) * settings.reward_to_risk)
        reason = "Bullish confluence confirmed on all closed timeframes."
    elif signal.signal == "STRONG SELL":
        side = "SHORT"
        action = "GO SHORT"
        entry = market.bid or market.price
        stop = entry * (1.0 + settings.stop_loss_percent)
        target = entry - ((stop - entry) * settings.reward_to_risk)
        reason = "Bearish confluence confirmed on all closed timeframes."
    else:
        return FuturesRecommendation(
            action="STAY FLAT",
            side="FLAT",
            confidence=abs(signal.score),
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            quantity_btc=0.0,
            notional=0.0,
            max_loss=0.0,
            leverage=settings.futures_leverage,
            reason="The closed-candle setup does not have full confirmation.",
        )

    stop_distance = abs(entry - stop)
    risk_budget = settings.paper_account_equity * settings.risk_per_trade
    risk_sized_quantity = risk_budget / stop_distance
    max_notional = (
        settings.paper_account_equity
        * settings.futures_leverage
        * settings.max_position_fraction
    )
    quantity = min(risk_sized_quantity, max_notional / entry)
    notional = quantity * entry
    max_loss = quantity * stop_distance

    return FuturesRecommendation(
        action=action,
        side=side,
        confidence=abs(signal.score),
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        quantity_btc=quantity,
        notional=notional,
        max_loss=max_loss,
        leverage=settings.futures_leverage,
        reason=reason,
    )
