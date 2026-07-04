# BTC Tri-Factor Terminal Bot

A terminal-based BTC/USDT market signal engine using multi-timeframe technical
confirmation, recent Bitcoin news sentiment, and a high-impact macro headline
filter. Confirmed signals are also translated into paper futures guidance:
`GO LONG`, `GO SHORT`, or `STAY FLAT`.

By default the program is intentionally **signal-only**. It does not request
exchange API keys and does not place orders. Futures entry, stop, target, size,
and maximum loss values are paper estimates for strategy validation. Binance
USD-M mode uses the public perpetual-contract quote as its reference. The only
order-capable mode is the explicit `BOT_ACTIVE_TRADER_EXECUTION=binance_demo`
path, which targets Binance Demo Trading rather than live Binance futures.

## Strategy

- Technical analysis, 40%: the existing 4-hour EMA 20/50, RSI 14, and MACD
  strategy contributes 60% of the technical score; daily EMA trend direction
  contributes 25%; and 1-hour entry timing contributes 15%.
- A `STRONG BUY` or `STRONG SELL` requires the 4-hour strategy direction,
  daily trend, and 1-hour entry timing to agree. Otherwise the result is held
  at `HOLD / NEUTRAL`.
- Bitcoin news sentiment, 30%: recency-weighted VADER sentiment from recent
  CoinDesk, Cointelegraph, Decrypt RSS headlines, GDELT market headlines, the
  Crypto Fear & Greed Index, and Binance USD-M derivatives crowding when
  available. Headlines are also classified into structured event buckets such
  as ETF flows, Fed/rates, CPI/inflation, jobs report, SEC/regulation,
  exchange security, liquidation cascade, whale transfer, and stablecoin risk.
- Macro factor, 30%: Federal Reserve, FOMC, rates, CPI, inflation, central-bank,
  regulation, and liquidation headlines from RSS and GDELT.
- A high-impact economic calendar risk layer watches configured events and a
  built-in recurring U.S. macro schedule approximation for CPI, PPI, jobs/NFP,
  and FOMC decision windows. It can reduce bullish confluence around event
  windows even when headlines are quiet.
- A detected negative macro event reduces any positive confluence score with a
  defensive multiplier. It does not suppress bearish signals.
- Score above `+0.65`: `STRONG BUY`; below `-0.65`: `STRONG SELL`; otherwise:
  `HOLD / NEUTRAL`.
- Regime-adaptive weighting (`BOT_ADAPTIVE_WEIGHTS`, on by default) conditions
  the technical timeframe weights and signal thresholds on the market-context
  regime: trending structure shifts weight toward the 4-hour strategy and daily
  trend (55/35/10), range structure raises the confirmation bar to `±0.70` and
  gives 1-hour entry timing more weight (50/20/30), and high volatility always
  raises thresholds to `±0.75`. Position sizing and risk settings are never
  changed by the profile, and the active profile is shown in the dashboards.
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
interest, the global long/short account ratio, top-trader account and position
ratios, taker buy/sell ratio, and a derivatives crowding score. These metrics
are confirmation context and also contribute a small source-level input inside
the existing 30% sentiment bucket when available; they do not add a new fourth
signal weight. It also listens to public order-book depth, aggregate trades, and liquidation
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

To keep Binance USD-M as the market-data backbone and add public Polymarket
Bitcoin prediction-market context to the sentiment bucket:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
$env:BOT_POLYMARKET_SENTIMENT = "true"
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

The dashboard is organized into six tabs: `Overview` (signal, confidence,
sentiment sources with per-asset chips, compact scanner, paper setup, and risk
cards), `Active Trader` (the always-on $100 5-minute BTC paper execution
account with its PnL growth curve and live execution cycle), `Long / Short Map`
(the interactive chart), `Scanner` (the full sortable multi-symbol table with
portfolio allocation status), `Performance` (the multi-symbol paper portfolio:
equity curve with concurrent-position bars, net R distribution, grouped win
rates, drift status, and the offline simulator), and `System` (signal profile,
meta model, portfolio limits, drift detail, refresh health, market context, and
recent errors).

Read-only JSON endpoints back the same data: `/api/setups` (recent journal
rows, filterable by `symbol`, `side`, `outcome`, and `limit`),
`/api/performance` (journal report with equity curve and drift plus portfolio
state), `/api/portfolio`, and `/api/drift`.

The dashboard includes a BTC Long / Short Map for visual trade context. It
draws recent 4-hour candles with EMA 20/50, VWAP, Bollinger bands,
support/resistance, the probabilistic 24-hour range, and a current
`GO LONG`, `GO SHORT`, or `STAY FLAT` marker. Indicator panels below the price
chart show RSI 14, MACD histogram, ADX 14, and volume. A Long / Short / Flat
meter summarizes the current directional bias from the existing signal and
paper futures guidance. This chart is designed to make confirmation and risk
context easier to read; it does not make predictions with certainty and does
not place trades.

The map is interactive in the React dashboard. Range buttons switch between
1-day, 3-day, 7-day, 14-day, 30-day, and full-history views; the chart can be
dragged horizontally to inspect older candles; and hover crosshairs show candle
OHLC, volume, RSI, MACD histogram, EMA values, ADX, and trend state. Overlay
toggles control EMA/VWAP, Bollinger bands, support/resistance, scenario paths,
paper setup entry/stop/take-profit lines, long/short zones, and the trend
ribbon.

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
| `BOT_SYMBOLS` | unset | Optional comma-separated symbols for the Long / Short Scanner |
| `BOT_MARKET_REFRESH_SECONDS` | `60` | REST fallback and futures-metrics interval |
| `BOT_NEWS_REFRESH_SECONDS` | `600` | Independent RSS refresh, minimum 60 |
| `BOT_STREAM_STALE_SECONDS` | `15` | Age before REST ticker fallback |
| `BOT_ANALYSIS_INTERVAL_HOURS` | `4` | Analysis boundary interval |
| `BOT_HTTP_TIMEOUT_SECONDS` | `12` | Exchange and news HTTP timeout |
| `BOT_HEADLINE_LIMIT` | `12` | Headlines shown in the dashboard |
| `BOT_POLYMARKET_SENTIMENT` | `false` | Include public Polymarket Bitcoin directional market probabilities as an optional sentiment source |
| `BOT_POLYMARKET_QUERY` | `bitcoin` | Polymarket search query used for prediction-market context |
| `BOT_POLYMARKET_MARKET_LIMIT` | `12` | Maximum directional Polymarket markets used per refresh |
| `BOT_ECONOMIC_CALENDAR` | `true` | Enable scheduled high-impact macro event watch |
| `BOT_ECONOMIC_CALENDAR_PATH` | unset | Optional JSON or CSV calendar file with `name`, `event_type`, `scheduled_at`, `impact` |
| `BOT_ECONOMIC_CALENDAR_LOOKAHEAD_HOURS` | `48` | Hours ahead to show configured or built-in macro events |
| `BOT_ECONOMIC_CALENDAR_PRE_EVENT_HOURS` | `6` | Hours before a scheduled event to apply event-risk multiplier |
| `BOT_ECONOMIC_CALENDAR_POST_EVENT_HOURS` | `2` | Hours after a scheduled event to keep event-risk multiplier active |
| `BOT_ADAPTIVE_WEIGHTS` | `true` | Condition signal weights/thresholds on the market regime |
| `BOT_PORTFOLIO_RISK` | `true` | Enable shared portfolio limits for paper setups |
| `BOT_PORTFOLIO_MAX_OPEN_POSITIONS` | `4` | Maximum concurrent open paper positions across symbols |
| `BOT_PORTFOLIO_MAX_SAME_DIRECTION` | `3` | Maximum correlated same-direction open positions |
| `BOT_PORTFOLIO_MAX_OPEN_RISK` | `0.02` | Total planned open risk as a fraction of paper equity |
| `BOT_PORTFOLIO_COOLDOWN_HOURS` | `8` | Per-symbol cooldown after a stop-loss outcome |
| `BOT_PORTFOLIO_MAX_DRAWDOWN_PERCENT` | `15` | Paper-ledger drawdown that activates the kill switch |
| `BOT_META_MODEL` | `true` | Enable the journal-trained TP-odds gate for new setups |
| `BOT_META_MIN_TRAINING_SAMPLES` | `40` | Resolved TP/SL setups required before the meta model trains |
| `BOT_META_MIN_TP_PROBABILITY` | `0.45` | Minimum estimated TP odds before a paper setup is allowed |
| `BOT_PAPER_ACCOUNT_EQUITY` | `10000` | Paper account value used for sizing |
| `BOT_RISK_PER_TRADE` | `0.005` | Maximum planned loss as equity fraction |
| `BOT_STOP_LOSS_PERCENT` | `0.015` | Stop distance from entry |
| `BOT_REWARD_TO_RISK` | `2.0` | Take-profit distance relative to stop |
| `BOT_FUTURES_LEVERAGE` | `5` | Paper leverage, capped at 5 |
| `BOT_MAX_POSITION_FRACTION` | `0.25` | Maximum margin allocation |
| `BOT_PAPER_LEDGER_FEE_RATE` | `0.0004` | Per-side fee rate used by the paper ledger net PnL model |
| `BOT_PAPER_LEDGER_SLIPPAGE_BPS` | `2.0` | Per-side slippage estimate in basis points for paper ledger net PnL |
| `BOT_PAPER_LEDGER_FUNDING_RATE_8H` | `0.0001` | Assumed 8-hour funding rate for paper ledger net PnL |
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
| `BOT_SCALPING_ENABLED` | `true` | Enable the independent closed-5-minute-candle scalping signal |
| `BOT_SCALPING_REFRESH_SECONDS` | `300` | How often the scalping signal re-evaluates on closed 5m candles |
| `BOT_SCALPING_BUY_THRESHOLD` | `0.50` | Scalping-only technical score above which the signal is bullish |
| `BOT_SCALPING_SELL_THRESHOLD` | `-0.50` | Scalping-only technical score below which the signal is bearish |
| `BOT_SCALPING_STOP_LOSS_PERCENT` | `0.003` | Scalping stop distance from entry (0.3%), independent of `BOT_STOP_LOSS_PERCENT` |
| `BOT_SCALPING_REWARD_TO_RISK` | `1.5` | Scalping take-profit distance relative to stop |
| `BOT_SCALPING_RISK_PER_TRADE` | `0.0025` | Scalping maximum planned loss as equity fraction |
| `BOT_SCALPING_HORIZON_HOURS` | `2` | Hours before an unresolved scalp setup is marked `EXPIRED` |
| `BOT_SCALPING_JOURNAL_PATH` | unset | Optional SQLite file, separate from `BOT_PAPER_SETUP_JOURNAL_PATH`, for scalp setup tracking |
| `BOT_ACTIVE_TRADER_ENABLED` | `true` | Enable the always-on 5-minute BTC active paper trader shown in the `Active Trader` tab |
| `BOT_ACTIVE_TRADER_EQUITY` | `100` | Starting paper balance for the active trader simulation |
| `BOT_ACTIVE_TRADER_MARGIN_USD` | `50` | Isolated paper margin committed to each active-trader futures fill before leverage |
| `BOT_ACTIVE_TRADER_REFRESH_SECONDS` | `1` | How often the active trader runs a new execution cycle |
| `BOT_ACTIVE_TRADER_RISK_PER_TRADE` | `0.02` | Legacy risk-based sizing input; active futures fills use `BOT_ACTIVE_TRADER_MARGIN_USD` |
| `BOT_ACTIVE_TRADER_JOURNAL_PATH` | `data/active-trader-fills.jsonl` | Append-only JSONL log of active-trader opens and settlements with PnL |
| `BOT_ACTIVE_TRADER_EXECUTION` | `paper` | `paper` local simulation or `binance_demo` market orders on Binance USD-M Demo Trading |
| `BOT_BINANCE_DEMO_API_KEY` | unset | Binance Demo Trading API key, required only for `BOT_ACTIVE_TRADER_EXECUTION=binance_demo` |
| `BOT_BINANCE_DEMO_API_SECRET` | unset | Binance Demo Trading API secret, required only for `BOT_ACTIVE_TRADER_EXECUTION=binance_demo` |
| `BOT_BINANCE_DEMO_BASE_URL` | `https://demo-fapi.binance.com` | Binance USD-M Demo Trading REST endpoint; live Binance endpoints are refused |
| `BOT_BINANCE_DEMO_RECV_WINDOW_MS` | `5000` | Signed request receive window for Binance Demo orders |
| `BOT_ACTIVE_TRADER_EARLY_TP_MODE` | `positive_roi` | Early take-profit mode: `disabled`, `positive_roi`, `min_roi`, or `progress` |
| `BOT_ACTIVE_TRADER_EARLY_TP_MIN_ROI_PERCENT` | `0.0` | Minimum net ROI on margin before an early active-trader TP is allowed |
| `BOT_ACTIVE_TRADER_REENTRY_MODE` | `immediate` | Same-cycle re-entry mode: `immediate`, `same_direction`, `flip_on_reversal`, or `disabled_after_exit` |
| `BOT_ACTIVE_TRADER_FLIP_THRESHOLD` | `0.50` | Minimum absolute 5m technical bias required to flip direction in `flip_on_reversal` mode |
| `BOT_ACTIVE_TRADER_COOLDOWN_CANDLES` | `3` | Same-side fill cooldown, in completed 5m candles, after `EXPIRED`, `STOP_LOSS`, or `PROTECTED_STOP` |
| `BOT_ACTIVE_TRADER_BREAKEVEN_PROGRESS_PERCENT` | `50.0` | Move the active-trader protected stop to breakeven once this percent of target progress is observed |
| `BOT_ACTIVE_TRADER_FORCE_PROFIT_PROGRESS_PERCENT` | `75.0` | In `progress` early-TP mode, require this percent of target progress before banking a profitable close |

To scan a multi-coin futures universe for paper long/short candidates, set
`BOT_SYMBOLS` before starting the terminal bot or web API:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
$env:BOT_SYMBOLS = "BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT,DOGE/USDT,ADA/USDT,LINK/USDT,AVAX/USDT,DOT/USDT,SUI/USDT"
btc-tri-factor-web
```

The scanner ranks each symbol with the same completed-candle technical
confirmation, current market sentiment, macro filter, and paper futures action
used by the main BTC view. Symbols are reported as `GO LONG`, `GO SHORT`,
`STAY FLAT`, or `UNAVAILABLE`. This scanner is still signal-only and does not
place orders.

Scanner symbols are fetched concurrently through cached per-symbol exchange
clients instead of a serial loop, so a large universe refreshes in a few
round-trips. Headlines are tagged per asset (ETH, SOL, XRP, and the rest of the
universe) and each scanned coin swaps the Bitcoin headline component of the
sentiment score for its own asset-tagged headlines when at least two are
available; Fear & Greed and derivatives crowding stay market-wide. The scanner
table reports whether each row used `asset` or `global` sentiment.

When a paper setup journal is configured, the scanner also records `GO LONG` /
`GO SHORT` candidates for non-primary symbols into the same journal and
resolves their outcomes from each symbol's public candles, which turns the
journal into a multi-symbol paper portfolio.

Portfolio risk limits (`BOT_PORTFOLIO_*`) treat all scanned crypto symbols as
one correlated group and gate every new paper setup, both the primary symbol
and scanner candidates: a maximum number of concurrent open paper positions, a
same-direction cap (five correlated longs behave like one oversized long), a
shared open-risk budget as a fraction of paper equity, a per-symbol cooldown
after a stop-loss, and a drawdown kill switch computed from the paper ledger.
Blocked candidates keep their raw signal but show the blocking reason, and the
current portfolio state is visible in the dashboard.

The meta model gate (`BOT_META_MODEL`, on by default) trains a small logistic
regression on resolved TP/SL journal outcomes (side, technical score, ATR,
range position, trend strength, reward/risk, and expected R). Once at least
`BOT_META_MIN_TRAINING_SAMPLES` resolved setups exist, it estimates TP odds for
each new directional setup and blocks paper guidance below
`BOT_META_MIN_TP_PROBABILITY`. Until then it reports `UNTRAINED` and never
blocks.

The journal report also includes a portfolio equity curve across all recorded
symbols with concurrent-position counts, and a performance drift monitor that
compares the recent win rate against the long-run baseline with a binomial
z-score, reporting `NORMAL`, `WARNING`, or `ALERT` when the live edge degrades.

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
It also computes a paper-trading ledger from the same rows, including gross
PnL, net PnL after estimated fees/slippage/funding, return percent, average
net R, and max drawdown. The web dashboard shows this compact live summary when
`BOT_PAPER_SETUP_JOURNAL_PATH` is set.
This paper setup layer is still signal-only and paper-only. It does not request
exchange credentials, call private APIs, place real orders, or auto-trade.

## 5-Minute Scalping System

`BOT_SCALPING_ENABLED` (on by default) runs a second, independent paper signal
on closed 5-minute candles alongside the main 4h-anchored system. It is
purely technical: it skips news and macro sentiment entirely, since those
are far too slow-moving to matter on a 5-minute horizon, and evaluates the
same EMA 20/50, RSI 14, and MACD scoring used elsewhere, re-checked every
`BOT_SCALPING_REFRESH_SECONDS` (5 minutes by default) against a closed 5m
candle. A score above `BOT_SCALPING_BUY_THRESHOLD` (`+0.50`) or below
`BOT_SCALPING_SELL_THRESHOLD` (`-0.50`) becomes `GO LONG` / `GO SHORT`;
otherwise the scalp signal stays flat.

Risk sizing is deliberately tight and configured separately from the main
system: `BOT_SCALPING_STOP_LOSS_PERCENT` (0.3%), `BOT_SCALPING_REWARD_TO_RISK`
(1.5), and `BOT_SCALPING_RISK_PER_TRADE` (0.25% of paper equity), since the
main system's 1.5%/2:1 swing-trade settings would rarely be touched by
5-minute price action. The same do-not-trade market-context filters used by
the main system (ATR ceiling, range-extreme chasing) still apply.

Setting `BOT_SCALPING_JOURNAL_PATH` records scalp setups into their own
SQLite journal, completely separate from `BOT_PAPER_SETUP_JOURNAL_PATH`.
This keeps the scalping system's win rate, meta-model training, and
portfolio limits from ever mixing with the main 4h system: a scalp trade on
BTC does not block or get blocked by the main BTC position, and resolved
scalp outcomes never feed the main meta-model gate. Only one open scalp
setup per symbol is allowed at a time; while one is open, new scalp signals
report `STAY FLAT` with a reason instead of stacking additional entries.
Unresolved setups expire after `BOT_SCALPING_HORIZON_HOURS` (2 hours).

Analyze recorded scalp setups with the same analyzer used for the main
paper journal:

```powershell
btc-paper-setups data/scalping-setups.sqlite
```

The web dashboard's Overview tab shows a `5-Minute Scalp Signal` card with
the current technical score, RSI, MACD histogram, paper entry/stop/target
when directional, and a compact summary of the scalp journal (total setups,
open count, win rate, expected R, net PnL) when `BOT_SCALPING_JOURNAL_PATH`
is set. The terminal dashboard shows the same signal as a `5m Scalp` line
inside the main signal panel. This layer is still signal-only and
paper-only: it does not request exchange credentials, place real orders, or
auto-trade.

## 5-Minute Active Trader

`BOT_ACTIVE_TRADER_ENABLED` (on by default) adds an always-on paper trading
account that refreshes every second against completed 5-minute BTC candles and is shown in its
own `Active Trader` dashboard tab. Unlike the scalping layer, which only
journals signals, the active trader holds one paper position at a time and
compounds a single balance seeded at `BOT_ACTIVE_TRADER_EQUITY` (default $100),
so the tab can chart realized **PnL growth** over the session.

Every `BOT_ACTIVE_TRADER_REFRESH_SECONDS` (1 second by default) it runs one
**execution cycle** with five gated stages:

- **Scam detect** - blocks the cycle when live shakeout/microstructure stress is
  `HIGH` (treated as possible manipulation).
- **Validate** - runs the same do-not-trade market-context filters used
  elsewhere (ATR ceiling, range-extreme chasing, and so on).
- **Size** - commits fixed isolated paper margin from
  `BOT_ACTIVE_TRADER_MARGIN_USD` (default $50) and applies
  `BOT_FUTURES_LEVERAGE` (default 5x), so the default active fill is about
  $250 notional.
- **Fill** - opens a paper position at the closed-candle entry when the account
  is flat; while another position is running, the cycle keeps preparing the
  current long/short candidate and waits to fill until the open position
  resolves.
- **Settle** - resolves the open position against later public closed candles as
  `TP`, `SL`, or `EXPIRED`, using the same conservative same-candle rule as the
  paper setup journal, then rolls the net PnL (after fees and slippage) into the
  balance.

Because the active trader refreshes every second and receives live mark-price
updates, an unresolved position with positive net ROI can be banked as an early
`TP` before the current 5-minute candle closes, even if the original take-profit
level was not touched. That realizes the gain, frees the account, and lets the
next 1-second cycle prepare or open the next paper trade when the setup still
clears. If no live early close occurs, the same logic is applied again when the
next completed 5-minute candle arrives.
Set `BOT_ACTIVE_TRADER_EARLY_TP_MODE` to `min_roi` to require
`BOT_ACTIVE_TRADER_EARLY_TP_MIN_ROI_PERCENT`, to `progress` to require both
positive net ROI and `BOT_ACTIVE_TRADER_FORCE_PROFIT_PROGRESS_PERCENT`, or to
`disabled` to keep profitable unresolved candles as `EXPIRED`.

Same-cycle re-entry is controlled by `BOT_ACTIVE_TRADER_REENTRY_MODE`.
`immediate` preserves the default behavior, `same_direction` only reopens in
the side that just settled, `flip_on_reversal` allows an opposite-side reopen
only when the absolute 5-minute technical bias reaches
`BOT_ACTIVE_TRADER_FLIP_THRESHOLD`, and `disabled_after_exit` waits until the
next execution cycle. When a candle reaches
`BOT_ACTIVE_TRADER_BREAKEVEN_PROGRESS_PERCENT` of the target before settlement,
the active-trader position tracks a protected breakeven stop for subsequent
resolution.
After an `EXPIRED`, `STOP_LOSS`, or `PROTECTED_STOP` exit,
`BOT_ACTIVE_TRADER_COOLDOWN_CANDLES` blocks same-side fills for a few completed
5-minute candles while the bot keeps scanning every cycle. The dashboard shows
this as a `COOLDOWN` fill-stage result instead of slowing the market analysis.

The tab shows starting and current equity, net PnL, return, win rate, max
drawdown, the live execution cycle, the current open position with unrealized
PnL, recent settled fills with exit reasons such as `EARLY_TP`, `TARGET_HIT`,
`PROTECTED_STOP`, `STOP_LOSS`, and `EXPIRED`, and the PnL growth curve (one
point per settled trade). Each paper open and settlement is appended to
`BOT_ACTIVE_TRADER_JOURNAL_PATH` (default `data/active-trader-fills.jsonl`)
with entry, exit, net PnL, net R, equity, drawdown, and setup context so losses
and gains can be reviewed after restart. The account balance itself is still a
session simulation and resets when the service restarts. This layer is still
paper-only: it does not request exchange
credentials, submit orders, or auto-trade. Position notional is the configured
paper margin multiplied by the configured leverage.
The Active Trader dashboard also graphs recent cycle outcomes across the
scam-detect, validate, size, fill, and settle stages, and raises a scam-detect
alert when high shakeout/manipulation risk blocks a setup.

To mirror the active-trader lifecycle with Binance USD-M Demo Trading market
orders, create Binance Demo Trading API credentials and opt in explicitly:

```powershell
$env:BOT_EXCHANGE = "binance-usdm"
$env:BOT_ACTIVE_TRADER_EXECUTION = "binance_demo"
$env:BOT_BINANCE_DEMO_API_KEY = "your-demo-key"
$env:BOT_BINANCE_DEMO_API_SECRET = "your-demo-secret"
btc-tri-factor-web
```

In `binance_demo` mode, the strategy still uses the same local validation,
sizing, and settlement logic, but a successful fill requires a signed demo
market order at `https://demo-fapi.binance.com`. Demo close orders are sent as
reduce-only market orders when the local TP, SL, expiry, or early-TP condition
resolves. Live Binance futures endpoints are refused by the demo client.

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

Run an offline multi-coin futures simulator against locally stored candles:

```powershell
$env:BOT_HISTORY_DB_PATH = "data/history.sqlite"
btc-futures-sim --exchange binance-usdm --symbols BTC/USDT,ETH/USDT,SOL/USDT,SUI/USDT --leverage 3 --fee-rate 0.0004 --funding-rate-8h 0.0001
```

The simulator replays completed 1-hour candles while aligning the latest
completed daily and 1-hour entry-timing candles for the same symbol. Use
`--primary-timeframe 4h` to compare the older 4-hour trade cadence, or pass
another synced public candle timeframe. Because historical
headline sentiment and macro state are not available from candle history, this
is a candle-only technical replay using the same multi-timeframe confirmation
gate as the live scanner. It reports win rate, gross and net expected R, net
PnL, fees, funding, return, max drawdown, liquidation-risk count, and
liquidation touches per symbol and overall. It uses public candles only, applies
conservative same-candle assumptions, and does not place orders.

Before simulating a symbol, sync all required timeframes:

```powershell
btc-history-sync --exchange binance-usdm --symbol SUI/USDT:USDT --timeframes 1h,4h,1d
```

Run a rolling walk-forward parameter evaluation over the same local history:

```powershell
$env:BOT_HISTORY_DB_PATH = "data/history.sqlite"
btc-walkforward --exchange binance-usdm --symbols BTC/USDT,ETH/USDT --folds 4 --test-days 21 --train-days 90
```

The harness replays every candidate parameter set (entry threshold, stop
percent, reward/risk via `--thresholds`, `--stops`, `--ratios`) over the full
candle history, then for each fold picks the best set on the train window and
scores it on the following unseen test window. The report shows per-fold
choices, out-of-sample trades, win rate, net expected R, and PnL, plus a pooled
out-of-sample comparison against the currently configured baseline. Judge
parameters by the pooled out-of-sample row, not the train rows; in-sample
selection can always overfit. This is an offline analysis tool only.

## Test

```powershell
pytest
```

## Development Context

The bot is organized as a small Python package with these responsibilities:

- `exchange.py`: public CCXT ticker, closed candles, and stream normalization.
- `realtime.py`: background CCXT Pro ticker and OHLCV WebSocket subscriptions.
- `indicators.py`: 4-hour technical analysis, multi-timeframe scoring, and chart-ready indicator series.
- `news.py`: Bitcoin and per-asset sentiment plus macro-risk analysis.
- `strategy.py`: weighted tri-factor score and final signal classification.
- `adaptive.py`: regime-conditioned signal weights and thresholds.
- `futures.py`: long/short/flat guidance and risk-based paper sizing.
- `scalping.py`: independent closed-5-minute-candle scalping signal, tight paper sizing, and its own journal.
- `active_trader.py`: always-on $100 5-minute BTC paper execution account with a compounding balance and realized PnL growth.
- `portfolio.py`: shared multi-symbol paper position limits and kill switch.
- `meta_model.py`: journal-trained logistic TP-odds gate for new setups.
- `backtest.py`: candle-only historical probability and TP/SL calibration.
- `walkforward.py`: rolling train/test parameter evaluation over local history.
- `microstructure.py`: rolling order-book, taker-flow, liquidation, and open-interest shakeout risk.
- `market_context.py`: volatility regime, range position, and trend/range context.
- `scanner.py`: concurrent multi-symbol scans, per-asset sentiment, and portfolio allocation.
- `app.py`: evaluation scheduling and service orchestration.
- `dashboard.py`: Rich terminal dashboard and static report.
- `web.py`: React dashboard API, server-sent events, static serving, and chart payloads.
- `models.py`: immutable analysis and evaluation data models.

The React dashboard source in `web/src` is organized into `lib/` (formatting
helpers and the snapshot SSE hook) and `components/` (header/tabs, signal,
news, confidence, scanner, performance, and system panels), with the
interactive Long / Short Map remaining in `main.jsx`.

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
with publishers and GDELT fetched concurrently so one slow feed cannot delay
every other source. A completed refresh also pulls the Crypto Fear & Greed Index
and immediately recalculates the signal while preserving the last valid news
analysis during a temporary feed outage.

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
refresh-health transitions, the independent 5-minute scalping signal and its
journal, and Windows console encoding.

## Risk Notice

This software provides a rules-based market signal, not financial advice.
Headline sentiment is noisy, RSS availability can change, and historical
indicator behavior does not guarantee future results. Validate the strategy
with backtesting and paper trading before using it in any financial workflow.
