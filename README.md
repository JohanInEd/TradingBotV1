# BTC Tri-Factor Terminal Bot

A terminal-based BTC/USDT market signal engine using multi-timeframe technical
confirmation, recent Bitcoin news sentiment, and a high-impact macro headline
filter. Confirmed signals are also translated into paper futures guidance:
`GO LONG`, `GO SHORT`, or `STAY FLAT`.

The program is intentionally **signal-only**. It does not request exchange API
keys and cannot place orders. Futures entry, stop, target, size, and maximum
loss values are paper estimates for strategy validation. Binance USD-M mode
uses the public perpetual-contract quote as its reference.

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

The dashboard adds a market-context layer from 4-hour candles: ATR percent,
realized volatility, Bollinger-band width, 50-candle range position, and
20/50-period trend spread. It labels volatility and structure regimes such as
compressed volatility, elevated volatility, trending up/down, or range
compression. These values are context for interpreting conditions and do not
change the established signal weights.

In Binance USD-M mode, the dashboard also displays public derivatives context:
mark and index price, perpetual basis, funding rate and countdown, open
interest, and the global long/short account ratio. These metrics are currently
confirmation context and do not alter the established 40/30/30 signal weights.
It also listens to public order-book depth, aggregate trades, and liquidation
events to estimate live shakeout-risk context. Depth, taker flow, large trades,
and liquidation stress are compared with recent rolling baselines and fade with
freshness decay instead of dropping out abruptly at the window edge. This is an
alerting layer for possible upside squeezes or downside stop runs, not a
prediction guarantee and not a trade trigger by itself.

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
btc-tri-factor --exchange binance-usdm
```

With `auto`, Kraken is attempted first and Binance second. No credentials are
needed because only public market endpoints are used.

For Binance USD-M perpetual market data, run:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
btc-tri-factor
```

For a persistent Windows CMD dashboard with UTF-8 output, run:

```bat
chcp 65001 >nul
set "PYTHONUTF8=1"
set "BOT_EXCHANGE=binance-usdm"
.venv\Scripts\python.exe -m btc_trading_bot
```

This resolves the default `BTC/USDT` setting to CCXT's linear perpetual symbol
`BTC/USDT:USDT` in both REST and WebSocket clients. It reads public Binance
USD-M data and produces paper guidance; it does not submit orders.

## Web Dashboard

The project also includes a React and Tailwind dashboard for live price, news,
macro risk, signal, and paper futures context. Start the Python live API:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
btc-tri-factor-web
```

Then run the React development server in a second terminal:

```powershell
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite dev server proxies `/api` requests to
the Python service on `http://127.0.0.1:8765`.

For a production-style local build:

```powershell
cd web
npm run build
cd ..
btc-tri-factor-web
```

After `web/dist` exists, `btc-tri-factor-web` serves the built interface from
`http://127.0.0.1:8765`. Live updates use server-sent events at
`/api/stream`, with `/api/snapshot` available for the current JSON state.

The dashboard includes a BTC Long / Short Map for visual trade context. It
draws recent 4-hour candles with EMA 20/50, VWAP, Bollinger bands,
support/resistance, the probabilistic 24-hour range, and a current
`GO LONG`, `GO SHORT`, or `STAY FLAT` marker. Indicator panels below the price
chart show RSI 14, MACD histogram, ADX 14, and volume. A Long / Short / Flat
meter summarizes the current directional bias from the existing signal and
paper futures guidance. This chart is designed to make confirmation and risk
context easier to read; it does not make predictions with certainty and does
not place trades.

The Long / Short Map also includes a muted 7-day scenario overlay built from
historical closed 4-hour candle setups with similar technical score, EMA trend,
RSI, MACD histogram, ATR/volatility context, and range position. It maps
historical percent-change paths onto the current BTC price to draw a median
path and probability band for the next 168 hours, plus up/down odds, confidence,
and sample counts. It is labeled as historical scenario analysis, not a
prediction, and remains paper-only/informational.

## Configuration

| Environment variable | Default | Description |
| --- | ---: | --- |
| `BOT_EXCHANGE` | `auto` | `auto`, `kraken`, `binance`, or `binance-usdm` |
| `BOT_SYMBOL` | `BTC/USDT` | CCXT symbol; USD-M mode adds `:USDT` when omitted |
| `BOT_MARKET_REFRESH_SECONDS` | `60` | REST fallback and futures-metrics interval |
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
| `BOT_PRICE_RANGE_HORIZON_HOURS` | `24` | Historical low/high estimate horizon |
| `BOT_PRICE_RANGE_LOOKBACK_CANDLES` | `180` | Recent 4h candles used for range samples |
| `BOT_PROBABILITY_HORIZON_HOURS` | `24` | Horizon for candle-only directional and TP/SL probability |
| `BOT_PROBABILITY_LOOKBACK_CANDLES` | `220` | Recent 4h candles used to find similar technical setups |
| `BOT_PROBABILITY_MIN_SAMPLES` | `30` | Minimum preferred similar samples before confidence is considered useful |
| `BOT_PROBABILITY_MAX_SAMPLES` | `120` | Maximum nearest historical setups used in the probability estimate |
| `BOT_DO_NOT_TRADE_FILTERS` | `true` | Enable risk gates that can block confirmed paper futures guidance |
| `BOT_TRADE_FILTER_REQUIRE_PROBABILITY` | `false` | Require probability forecast availability before allowing a paper setup |
| `BOT_TRADE_FILTER_MIN_PROBABILITY_SAMPLES` | `30` | Minimum similar samples required when probability data is available |
| `BOT_TRADE_FILTER_MIN_EXPECTED_R` | `0.0` | Minimum side-specific expected R before allowing a paper setup |
| `BOT_TRADE_FILTER_MAX_ATR_PERCENT` | `3.0` | Maximum 4h ATR percent allowed before blocking a paper setup |
| `BOT_TRADE_FILTER_RANGE_EXTREME_PERCENT` | `85.0` | Upper/lower 50-candle range extreme used to avoid chasing entries |
| `BOT_TRADE_FILTER_FUNDING_EXTREME` | `0.0005` | Funding threshold used with crowding to block stretched futures positioning |
| `BOT_TRADE_FILTER_LONG_SHORT_EXTREME` | `1.8` | Long/short crowding threshold, inverted for crowded shorts |
| `BOT_SHAKEOUT_WINDOW_SECONDS` | `300` | Rolling window for order-flow and liquidation stress |
| `BOT_SHAKEOUT_BASELINE_WINDOW_SECONDS` | `3600` | Recent history used to normalize shakeout stress against local baselines |
| `BOT_WHALE_TRADE_USD` | `1000000` | Minimum notional for a large taker trade alert |
| `BOT_SHAKEOUT_EVENT_LOG` | unset | Optional JSONL file for recording shakeout inputs and replay analysis |
| `BOT_SIGNAL_JOURNAL_PATH` | unset | Optional JSONL file for closed-candle signal evaluations and later outcome analysis |
| `BOT_PAPER_SETUP_JOURNAL_PATH` | unset | Optional SQLite file for closed-candle GO LONG / GO SHORT paper setup tracking |
| `BOT_PAPER_SETUP_HORIZON_HOURS` | `24` | Hours before an unresolved paper setup is marked `EXPIRED` |
| `BOT_HISTORY_DB_PATH` | unset | Optional SQLite file for public OHLCV history used by offline analysis and probability calibration |

To record live public depth, aggregate trade, liquidation, open-interest, and
top-trader crowding inputs for later shakeout review:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
$env:BOT_SHAKEOUT_EVENT_LOG = "data/shakeout-events.jsonl"
btc-tri-factor-web
```

Replay the file with the current monitor logic and compare it with recorded
baseline summaries embedded in the JSONL:

```powershell
btc-shakeout-backtest data/shakeout-events.jsonl
```

The replay summarizes current risk states, average score, peak score, peak
reason, and, when available, the original recorded status/score summary plus
the peak-score delta. Use `--window-seconds`, `--baseline-window-seconds`, or
`--whale-trade-usd` to compare alternate shakeout-scoring assumptions. The
replay does not change the live signal matrix and does not create trade
triggers.

To keep a local journal of each closed-candle evaluation, set
`BOT_SIGNAL_JOURNAL_PATH` before running the terminal bot or web API:

```powershell
$env:BOT_SIGNAL_JOURNAL_PATH = "data/signal-journal.jsonl"
btc-tri-factor-web
```

The journal appends one JSONL row per exchange, symbol, timeframe, and closed
candle timestamp. Rows include the closed candle OHLC, technical score, final
signal, paper futures guidance, sentiment and macro state, market context,
futures/shakeout context, and probability forecast. Duplicate rows for the same
closed candle are skipped.

Replay the journal after enough future candles have been recorded:

```powershell
btc-signal-journal data/signal-journal.jsonl
```

The analyzer reports completed 24-hour samples, direction accuracy, signaled
win rate, TP/SL-first outcomes for hypothetical long and short plans, expected
R, and grouped counts by signal, score bucket, sentiment, macro risk, market
regime, and futures/shakeout context. This is an offline analysis tool only; it
does not place orders or change live signal behavior.

To record only the closed-candle setups where the current futures guidance is
`GO LONG` or `GO SHORT`, set a paper setup journal path:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
$env:BOT_PAPER_SETUP_JOURNAL_PATH = "data/paper-setups.sqlite"
$env:BOT_PAPER_SETUP_HORIZON_HOURS = "24"
btc-tri-factor-web
```

The web dashboard shows a clearly labeled `paper setup` card when a closed
candle produces `GO LONG` or `GO SHORT`. It displays the paper entry, stop loss,
take profit, reward/risk, max loss, and position estimate from the existing
paper futures guidance. The card explicitly says `no order placed` and `not
financial advice`. When guidance is `STAY FLAT`, the dashboard keeps this area
compact and does not imply a paper trade is active.

Do-not-trade filters run after a confirmed closed-candle futures setup is built.
They can keep the raw signal intact while changing paper futures guidance to
`STAY FLAT` when probability odds, expected R, ATR, range location, shakeout
risk, or futures crowding are unfavorable. The dashboard shows the filter
status and the specific reason for any blocked paper setup.

The setup journal stores public-market-data audit fields for each setup:
exchange, symbol, timeframe, closed candle timestamp, signal time, side, entry,
stop loss, take profit, close price, technical score, futures action, market
context, probability forecast, and outcome columns. Duplicate setup rows are
skipped using exchange, symbol, timeframe, closed candle timestamp, side, entry,
stop loss, and take profit.

Outcome resolution uses only public OHLCV candles. During live evaluation the
bot queries only unresolved setup rows for the current market/timeframe and
checks them against the recent closed-candle window, keeping memory bounded.
Outcomes are `OPEN`, `TP`, `SL`, or `EXPIRED`. A setup is `TP` when take profit
is hit before stop loss, `SL` when stop loss is hit before take profit, and
`EXPIRED` when the configured horizon passes without either exit. The
conservative same-candle rule is: if TP and SL are both inside one public candle
after entry is observed, the journal records `SL` because intrabar order is
unknown.

Analyze recorded paper setups with:

```powershell
btc-paper-setups data/paper-setups.sqlite
```

The analyzer reports total setups, open setups, TP count, SL count, expired
count, win rate, expected R, average time to outcome, and grouped results by
side, score bucket, market regime, volatility regime, and trend/range context.
The web dashboard also shows a compact live summary from this same SQLite
journal when `BOT_PAPER_SETUP_JOURNAL_PATH` is set.
This paper setup layer is still signal-only and paper-only. It does not request
exchange credentials, call private APIs, place real orders, or auto-trade.

To keep a local store of public historical candles, set `BOT_HISTORY_DB_PATH`
and run `btc-history-sync` for the exchange, symbol, and timeframes you want to
cache:

```powershell
$env:BOT_HISTORY_DB_PATH = "data/history.sqlite"
btc-history-sync --exchange binance-usdm --symbol BTC/USDT:USDT --timeframes 1h,4h,1d
```

The recommended timeframes are `1h`, `4h`, and `1d`: 1-hour candles support
entry-timing research, 4-hour candles match the official signal/probability
analysis, and daily candles provide trend context. The sync command stores only
public OHLCV candles in SQLite, deduplicated by exchange, symbol, timeframe,
and timestamp. It does not request exchange credentials, place orders, or trade.

When `BOT_HISTORY_DB_PATH` is set and enough continuous local 4-hour history is
available, the live probability backtest uses a bounded recent slice from the
SQLite store plus the current exchange-fetched candle window. If local history
is missing or too short, it falls back to the existing exchange-fetched window.
Signal thresholds and paper guidance are unchanged.

Analyze stored public candle history without fetching new data:

```powershell
btc-history-sync --analyze --exchange binance-usdm --symbol BTC/USDT:USDT --timeframes 1h,4h,1d
```

The analyzer computes EMA 20/50, RSI 14, MACD, ATR percent, Bollinger width,
realized volatility, range position, trend spread, 4h/12h/24h forward movement,
long and short TP/SL first-hit outcomes, and expected R. Results are grouped by
timeframe, score bucket, market regime, volatility regime, trend/range context,
future movement bucket, and long/short TP/SL outcome.

## Test

```powershell
pytest
```

## Development Context

The bot is organized as a small Python package with these responsibilities:

- `exchange.py`: public CCXT ticker, closed candles, and stream normalization.
- `realtime.py`: background CCXT Pro ticker and OHLCV WebSocket subscriptions.
- `indicators.py`: 4-hour technical analysis, multi-timeframe scoring, and chart-ready indicator series.
- `news.py`: Bitcoin sentiment and macro-risk analysis.
- `strategy.py`: weighted tri-factor score and final signal classification.
- `futures.py`: long/short/flat guidance and risk-based paper sizing.
- `backtest.py`: candle-only historical probability and TP/SL calibration.
- `microstructure.py`: rolling order-book, taker-flow, liquidation, and open-interest shakeout risk.
- `market_context.py`: volatility regime, range position, and trend/range context.
- `app.py`: evaluation scheduling and service orchestration.
- `dashboard.py`: Rich terminal dashboard and static report.
- `web.py`: React dashboard API, server-sent events, static serving, and chart payloads.
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
existing REST client resumes polling. RSS news refreshes in a dedicated worker,
with publishers fetched concurrently so one slow feed cannot delay every other
source. A completed refresh immediately recalculates the signal while preserving
the last valid news analysis during a temporary feed outage.

The web snapshot also exposes compact chart data from the current 4-hour candle
set. Each row includes OHLCV plus EMA 20/50, VWAP, Bollinger bands, RSI 14,
MACD, MACD signal, MACD histogram, and ADX 14 values. The React dashboard uses
this payload to render the Long / Short Map without requiring a separate chart
API or third-party charting package.

The evaluation also estimates a historical low/high range for the next 24 hours
by reviewing prior forward windows from recent 4-hour candles. This is a
probabilistic support/resistance context, not a guaranteed forecast.

The evaluation also runs a candle-only probability backtest against recent
similar 4-hour technical setups. It reports the historical odds that price
closed up or down over the configured horizon, whether a paper long or short
would have reached take-profit before stop-loss, and the expected R multiple
for each side. This probability layer calibrates the current technical setup
from candle history only; it does not reconstruct historical news or macro
sentiment unless those are separately recorded in a live journal.

The 7-day scenario map uses the same closed-candle principle over a longer
168-hour horizon. It selects nearest historical setups, converts each following
7-day path into percent changes, and remaps the median and 20th/80th percentile
paths onto the latest BTC price. If there are not enough comparable historical
paths, the API returns `null` for the scenario forecast and the dashboard keeps
the overlay empty.

In Binance USD-M mode, the live stream additionally subscribes to public
top-of-book depth, aggregate market trades, and force-liquidation snapshots.
The shakeout monitor scores visible stress from thin bid/ask liquidity,
aggressive taker flow, large notional trades, liquidation bursts, open-interest
changes, and top-trader long/short crowding. Reason text includes the measured
driver, baseline comparison where available, and whether the risk context
agrees or conflicts with the main closed-candle signal. The terminal and web
dashboards also show separate depth, aggregate-trade, and force-liquidation
stream health with event counts and last-event age. Public order books can be
spoofed and do not identify wallets, so the output is treated as risk context
rather than proof of whale intent.

The header reports independent Market, Futures, and News refresh health. Each
source shows its current state, age of the last successful update, and next
scheduled refresh. Failed refreshes preserve the last valid data and change the
health state to `DEGRADED`, `FAILED`, or `RECONNECTING`.

Console output is configured to replace characters unsupported by the active
Windows code page instead of terminating the Rich dashboard. UTF-8 CMD launch
settings are still recommended for correctly displaying international headlines.

The current test suite covers indicators, multi-timeframe scoring, confirmation
gating, live ticker normalization, provisional candle merging, stale-stream
fallback, independent news updates, strategy weighting, futures guidance, risk
sizing, news analysis, Binance USD-M market resolution, concurrent RSS fetches,
futures-specific indicators, shakeout replay and stream-health behavior,
refresh-health transitions, and Windows console encoding.

## Risk Notice

This software provides a rules-based market signal, not financial advice.
Headline sentiment is noisy, RSS availability can change, and historical
indicator behavior does not guarantee future results. Validate the strategy
with backtesting and paper trading before using it in any financial workflow.
