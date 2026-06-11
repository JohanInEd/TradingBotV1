# BTC Tri-Factor Terminal Bot

A terminal-based BTC/USDT market signal engine using multi-timeframe technical
confirmation, recent Bitcoin news sentiment, and a high-impact macro headline
filter. Confirmed signals are also translated into paper futures guidance:
`GO LONG`, `GO SHORT`, or `STAY FLAT`.

The program is intentionally **signal-only**. It does not request exchange API
keys and cannot place orders. Futures entry, stop, target, size, and maximum
loss values are paper estimates for strategy validation. They currently use
the spot BTC/USDT price as a reference, not a perpetual-contract quote.

## Strategy

- Technical analysis, 40%: the existing 4-hour EMA 20/50, RSI 14, and MACD
  strategy contributes 60% of the technical score; daily EMA trend direction
  contributes 25%; and 1-hour entry timing contributes 15%.
- A `STRONG BUY` or `STRONG SELL` requires the 4-hour strategy direction,
  daily trend, and 1-hour entry timing to agree. Otherwise the result is held
  at `HOLD / NEUTRAL`.
- Bitcoin news sentiment, 30%: recency-weighted VADER sentiment from recent
  CoinDesk, Cointelegraph, and Decrypt RSS headlines.
- Macro factor, 30%: Federal Reserve, FOMC, rates, CPI, inflation, central-bank,
  regulation, and liquidation headlines.
- A detected negative macro event reduces any positive confluence score with a
  defensive multiplier. It does not suppress bearish signals.
- Score above `+0.65`: `STRONG BUY`; below `-0.65`: `STRONG SELL`; otherwise:
  `HOLD / NEUTRAL`.
- `STRONG BUY` becomes `GO LONG`; `STRONG SELL` becomes `GO SHORT`; every
  unconfirmed setup becomes `STAY FLAT`.
- Futures size is estimated from paper equity, stop distance, configured risk,
  leverage, and a maximum position cap.

Official signals use only completed 4-hour, daily, and 1-hour candles. The live
dashboard also shows clearly labeled provisional multi-timeframe values from
WebSocket candle updates. Ticker price, bid, ask, and 24-hour change stream in
real time, with REST polling retained as a stale-stream fallback. News and
macro analysis refresh independently every ten minutes.

## Install

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Run

```powershell
btc-tri-factor
```

Evaluate once without the live screen:

```powershell
btc-tri-factor --once
```

Select an exchange explicitly:

```powershell
btc-tri-factor --exchange kraken
btc-tri-factor --exchange binance
```

With `auto`, Kraken is attempted first and Binance second. No credentials are
needed because only public market endpoints are used.

For Binance market data, run:

```powershell
$env:BOT_EXCHANGE = "binance"
btc-tri-factor
```

The current implementation reads Binance spot BTC/USDT data and produces paper
futures guidance. It does not connect to Binance USD-M Futures or submit orders.

## Configuration

| Environment variable | Default | Description |
| --- | ---: | --- |
| `BOT_EXCHANGE` | `auto` | `auto`, `kraken`, or `binance` |
| `BOT_SYMBOL` | `BTC/USDT` | CCXT spot symbol |
| `BOT_MARKET_REFRESH_SECONDS` | `60` | REST ticker fallback interval |
| `BOT_NEWS_REFRESH_SECONDS` | `600` | Independent RSS refresh, minimum 60 |
| `BOT_STREAM_STALE_SECONDS` | `15` | Age before REST ticker fallback |
| `BOT_ANALYSIS_INTERVAL_HOURS` | `4` | Analysis boundary interval |
| `BOT_HTTP_TIMEOUT_SECONDS` | `12` | Exchange and news HTTP timeout |
| `BOT_HEADLINE_LIMIT` | `12` | Headlines shown in the dashboard |
| `BOT_PAPER_ACCOUNT_EQUITY` | `10000` | Paper account value used for sizing |
| `BOT_RISK_PER_TRADE` | `0.005` | Maximum planned loss as equity fraction |
| `BOT_STOP_LOSS_PERCENT` | `0.015` | Stop distance from entry |
| `BOT_REWARD_TO_RISK` | `2.0` | Take-profit distance relative to stop |
| `BOT_FUTURES_LEVERAGE` | `1` | Paper leverage, capped at 3 |
| `BOT_MAX_POSITION_FRACTION` | `0.25` | Maximum margin allocation |

## Test

```powershell
pytest
```

## Development Context

The bot is organized as a small Python package with these responsibilities:

- `exchange.py`: public CCXT ticker, closed candles, and stream normalization.
- `realtime.py`: background CCXT Pro ticker and OHLCV WebSocket subscriptions.
- `indicators.py`: 4-hour technical analysis and multi-timeframe scoring.
- `news.py`: Bitcoin sentiment and macro-risk analysis.
- `strategy.py`: weighted tri-factor score and final signal classification.
- `futures.py`: long/short/flat guidance and risk-based paper sizing.
- `app.py`: evaluation scheduling and service orchestration.
- `dashboard.py`: Rich terminal dashboard and static report.
- `models.py`: immutable analysis and evaluation data models.

The technical factor now combines:

- 60% from the primary 4-hour EMA, RSI, and MACD strategy.
- 25% from daily EMA 20/50 trend direction.
- 15% from 1-hour EMA, RSI, and MACD entry timing.

Strong directional signals require the 4-hour strategy, daily trend, and 1-hour
entry timing to agree. Conflicting confirmation produces `HOLD / NEUTRAL`
without changing the underlying confluence score. All three analyses use only
completed candles.

The dashboard receives live ticker and provisional `4h`, `1d`, and `1h` candle
updates through WebSockets. Provisional calculations are informational and do
not replace the closed-candle signal. If the ticker stream becomes stale, the
existing REST client resumes polling. RSS news refreshes in a dedicated worker
and immediately recalculates the signal while preserving the last valid news
analysis during a temporary feed outage.

The current test suite covers indicators, multi-timeframe scoring, confirmation
gating, live ticker normalization, provisional candle merging, stale-stream
fallback, independent news updates, strategy weighting, futures guidance, risk
sizing, and news analysis. At the time this context was recorded, all 20 tests
passed.

## Risk Notice

This software provides a rules-based market signal, not financial advice.
Headline sentiment is noisy, RSS availability can change, and historical
indicator behavior does not guarantee future results. Validate the strategy
with backtesting and paper trading before using it in any financial workflow.
