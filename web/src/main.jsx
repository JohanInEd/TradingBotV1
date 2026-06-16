import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [connection, setConnection] = useState("connecting");
  const [error, setError] = useState(null);
  const connectionRef = useRef("connecting");

  useEffect(() => {
    let cancelled = false;

    function updateConnection(nextConnection) {
      connectionRef.current = nextConnection;
      setConnection(nextConnection);
    }

    async function loadInitialSnapshot() {
      try {
        const response = await fetch("/api/snapshot");
        if (!response.ok) {
          throw new Error(`Snapshot failed: ${response.status}`);
        }
        const payload = await response.json();
        if (!cancelled) {
          setSnapshot(payload);
          updateConnection("polling");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          updateConnection("offline");
        }
      }
    }

    loadInitialSnapshot();

    const stream = new EventSource("/api/stream");
    stream.addEventListener("open", () => {
      if (!cancelled) updateConnection("live");
    });
    stream.addEventListener("snapshot", (event) => {
      if (!cancelled) {
        setSnapshot(JSON.parse(event.data));
        updateConnection("live");
        setError(null);
      }
    });
    stream.addEventListener("error", () => {
      if (!cancelled) updateConnection("reconnecting");
    });

    const poll = window.setInterval(async () => {
      if (cancelled || connectionRef.current === "live") return;
      try {
        const response = await fetch("/api/snapshot");
        const payload = await response.json();
        if (!cancelled) setSnapshot(payload);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }, 10000);

    return () => {
      cancelled = true;
      stream.close();
      window.clearInterval(poll);
    };
  }, []);

  const evaluation = snapshot?.evaluation;
  const market = evaluation?.market;
  const signal = evaluation?.signal;
  const sentiment = evaluation?.sentiment;
  const macro = evaluation?.macro;
  const futures = evaluation?.futures;
  const futuresMetrics = evaluation?.futures_metrics;
  const priceRange = evaluation?.price_range;
  const marketContext = evaluation?.market_context;
  const shakeout = evaluation?.shakeout;

  const allHeadlines = useMemo(() => {
    const crypto = sentiment?.headlines ?? [];
    const alerts = macro?.alerts ?? [];
    return [...crypto, ...alerts]
      .sort((a, b) => new Date(b.published_at) - new Date(a.published_at))
      .slice(0, 14);
  }, [sentiment, macro]);

  return (
    <main className="min-h-screen bg-ink text-slate-100">
      <div className="absolute inset-0 -z-0 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.18),transparent_32rem),radial-gradient(circle_at_80%_20%,rgba(132,204,22,0.12),transparent_26rem)]" />
      <div className="relative mx-auto flex max-w-7xl flex-col gap-6 px-5 py-6 lg:px-8">
        <Header connection={connection} error={error} updatedAt={snapshot?.generated_at} />

        {!evaluation ? (
          <LoadingPanel />
        ) : (
          <>
            <section className="grid gap-4 lg:grid-cols-6">
              <MetricCard
                label={`${market.exchange} ${market.symbol}`}
                value={formatUsd(market.price)}
                detail={`${formatPct(market.change_24h)} 24h - ${market.source}`}
                tone={market.change_24h >= 0 ? "positive" : "negative"}
              />
              <MetricCard
                label="Signal"
                value={signal.signal}
                detail={`Score ${formatNumber(signal.score, 3)} / Raw ${formatNumber(signal.raw_score, 3)}`}
                tone={signal.score > 0.2 ? "positive" : signal.score < -0.2 ? "negative" : "neutral"}
              />
              <MetricCard
                label="News Sentiment"
                value={sentiment.label}
                detail={`Weighted ${formatNumber(sentiment.score, 3)} - ${evaluation.news_health.status}`}
                tone={sentiment.score > 0.15 ? "positive" : sentiment.score < -0.15 ? "negative" : "neutral"}
              />
              <MetricCard
                label="Macro Filter"
                value={macro.status}
                detail={`Multiplier ${formatNumber(macro.risk_multiplier, 2)} - Score ${formatNumber(macro.score, 3)}`}
                tone={macro.risk_multiplier < 1 ? "negative" : "neutral"}
              />
              <MetricCard
                label={`${priceRange?.horizon_hours ?? 24}h Hist. Range`}
                value={`${formatUsd(priceRange?.expected_low)} / ${formatUsd(priceRange?.expected_high)}`}
                detail={`Confidence ${priceRange?.confidence ?? "-"} - ${priceRange?.sample_size ?? 0} samples`}
                tone="neutral"
              />
              <MetricCard
                label="Market Regime"
                value={marketContext?.volatility_regime ?? "WAITING"}
                detail={`${marketContext?.structure_regime ?? "Closed candle context"} - ATR ${formatPct(marketContext?.atr_percent)}`}
                tone={marketContext?.volatility_regime === "HIGH VOLATILITY" ? "negative" : marketContext?.volatility_regime === "ELEVATED VOLATILITY" ? "warning" : "neutral"}
              />
              <MetricCard
                label="Shakeout Risk"
                value={shakeout?.status ?? "WAITING"}
                detail={`${shakeout?.direction ?? "Microstructure stream"} - ${formatNumber(shakeout?.score, 2)} - ${shakeoutSignalContext(shakeout, signal)}`}
                tone={shakeout?.status === "HIGH" ? "negative" : shakeout?.status === "MEDIUM" ? "warning" : "neutral"}
              />
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              <SignalPanel evaluation={evaluation} futures={futures} futuresMetrics={futuresMetrics} priceRange={priceRange} shakeout={shakeout} />
              <NewsPanel headlines={allHeadlines} />
            </section>

            <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
              <HealthPanel evaluation={evaluation} />
              <MarketContextPanel marketContext={marketContext} />
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function Header({ connection, error, updatedAt }) {
  return (
    <header className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-glow backdrop-blur">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.35em] text-cyan-200">BTC Tri-Factor</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-5xl">
            Live market and news command center
          </h1>
          <p className="mt-3 max-w-2xl text-sm text-slate-300">
            Price streams through the Python service, while news sentiment and macro risk refresh on their own cadence.
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${connectionClass(connection)}`} />
            <span className="font-medium capitalize">{connection}</span>
          </div>
          <p className="mt-1 text-slate-400">Updated {formatTime(updatedAt)}</p>
          {error ? <p className="mt-1 text-rose-300">{error}</p> : null}
        </div>
      </div>
    </header>
  );
}

function MetricCard({ label, value, detail, tone }) {
  const toneClass = {
    positive: "text-emerald-300",
    negative: "text-rose-300",
    warning: "text-amber-200",
    neutral: "text-cyan-200"
  }[tone ?? "neutral"];

  return (
    <article className="rounded-3xl border border-white/10 bg-panel/80 p-5 shadow-glow">
      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">{label}</p>
      <p className={`mt-3 text-2xl font-semibold ${toneClass}`}>{value}</p>
      <p className="mt-2 text-sm text-slate-400">{detail}</p>
    </article>
  );
}

function SignalPanel({ evaluation, futures, futuresMetrics, priceRange, shakeout }) {
  const technical = evaluation.live_technical ?? evaluation.technical;
  const shakeoutContext = shakeoutSignalContext(shakeout, evaluation.signal);
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Trading Context</h2>
          <p className="text-sm text-slate-400">Closed-candle signal with live provisional technical context.</p>
        </div>
        <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-sm text-cyan-100">
          {evaluation.stream_status}
        </span>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <MiniStat label="4h technical" value={formatNumber(technical.score, 3)} />
        <MiniStat label="RSI 14" value={formatNumber(technical.rsi14, 2)} />
        <MiniStat label="MACD hist" value={formatNumber(technical.macd_histogram, 3)} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl bg-black/20 p-4">
          <p className="text-sm font-medium text-slate-200">Paper futures guidance</p>
          <p className="mt-2 text-3xl font-semibold text-cyan-200">{futures?.action ?? "STAY FLAT"}</p>
          <p className="mt-2 text-sm text-slate-400">{futures?.reason}</p>
          <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-slate-300">
            <span>Entry {formatUsd(futures?.entry_price)}</span>
            <span>Stop {formatUsd(futures?.stop_loss)}</span>
            <span>Target {formatUsd(futures?.take_profit)}</span>
            <span>Max loss {formatUsd(futures?.max_loss)}</span>
          </div>
        </div>
        <div className="rounded-2xl bg-black/20 p-4">
          <p className="text-sm font-medium text-slate-200">Derivatives context</p>
          <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300">
            <MiniLine label="Mark" value={formatUsd(futuresMetrics?.mark_price)} />
            <MiniLine label="Index" value={formatUsd(futuresMetrics?.index_price)} />
            <MiniLine label="Funding" value={formatPct((futuresMetrics?.funding_rate ?? 0) * 100, 4)} />
            <MiniLine label="Long/short" value={formatNumber(futuresMetrics?.long_short_ratio, 2)} />
          </div>
        </div>
      </div>

      {shakeout ? (
        <div className="mt-4 rounded-2xl border border-amber-300/20 bg-amber-300/10 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-sm font-medium text-amber-100">Public microstructure shakeout risk</p>
              <p className="mt-2 text-2xl font-semibold text-slate-100">
                {shakeout.status} - {shakeout.direction}
              </p>
              <p className="mt-2 text-sm text-slate-300">{shakeout.reason}</p>
              <p className="mt-2 text-xs uppercase tracking-[0.18em] text-amber-100">{shakeoutContext}</p>
            </div>
            <div className="grid min-w-64 grid-cols-2 gap-2 rounded-xl bg-black/20 p-3 text-sm text-slate-300">
              <MiniLine label="Score" value={formatNumber(shakeout.score, 2)} />
              <MiniLine label="Book" value={formatNumber(shakeout.order_book_imbalance, 2)} />
              <MiniLine label="Bid depth" value={formatCompactUsd(shakeout.bid_depth_usd)} />
              <MiniLine label="Ask depth" value={formatCompactUsd(shakeout.ask_depth_usd)} />
              <MiniLine label="Taker buy" value={formatCompactUsd(shakeout.taker_buy_usd)} />
              <MiniLine label="Taker sell" value={formatCompactUsd(shakeout.taker_sell_usd)} />
              <MiniLine label="Liq buy" value={formatCompactUsd(shakeout.liquidation_buy_usd)} />
              <MiniLine label="Liq sell" value={formatCompactUsd(shakeout.liquidation_sell_usd)} />
              <MiniLine label="Large trades" value={shakeout.large_trade_count} />
              <MiniLine label="OI change" value={formatPct(shakeout.open_interest_change_percent)} />
            </div>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            <div className="rounded-xl bg-black/20 p-3 text-sm text-slate-300">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Vs rolling baseline</p>
              <MiniLine label="Depth" value={formatRatio(shakeout.depth_stress_ratio)} />
              <MiniLine label="Taker flow" value={formatRatio(shakeout.taker_flow_stress_ratio)} />
              <MiniLine label="Large trades" value={formatRatio(shakeout.large_trade_stress_ratio)} />
              <MiniLine label="Liquidations" value={formatRatio(shakeout.liquidation_stress_ratio)} />
            </div>
            <div className="rounded-xl bg-black/20 p-3 text-sm text-slate-300">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Stream health</p>
              {(shakeout.stream_health ?? []).map((stream) => (
                <MiniLine
                  key={stream.name}
                  label={stream.name}
                  value={`${stream.status} - ${formatAgeSeconds(stream.last_event_age_seconds)} - ${stream.event_count}`}
                />
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {priceRange ? (
        <div className="mt-4 rounded-2xl border border-cyan-300/20 bg-cyan-300/10 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-sm font-medium text-cyan-100">
                Historical low/high estimate for next {priceRange.horizon_hours}h
              </p>
              <p className="mt-2 text-sm text-slate-300">
                Likely lower area {formatUsd(priceRange.expected_low)} ({formatPct(priceRange.downside_percent)})
                {" "}and likely upper area {formatUsd(priceRange.expected_high)} ({formatPct(priceRange.upside_percent)}).
              </p>
              <p className="mt-2 text-xs text-slate-400">{priceRange.method}</p>
            </div>
            <div className="min-w-56 rounded-xl bg-black/20 p-3 text-sm text-slate-300">
              <MiniLine label="Support" value={formatUsd(priceRange.support_level)} />
              <MiniLine label="Resistance" value={formatUsd(priceRange.resistance_level)} />
              <MiniLine label="Confidence" value={priceRange.confidence} />
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function NewsPanel({ headlines }) {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Real-Time News</h2>
      <p className="text-sm text-slate-400">Latest crypto headlines and macro alerts used by the model.</p>
      <div className="mt-5 space-y-3">
        {headlines.length ? (
          headlines.map((headline) => (
            <a
              key={`${headline.source}-${headline.title}`}
              href={headline.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="block rounded-2xl border border-white/10 bg-black/20 p-4 transition hover:border-cyan-300/50 hover:bg-cyan-300/10"
            >
              <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                <span>{headline.source} - {headline.category}</span>
                <span>{formatTime(headline.published_at)}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-100">{headline.title}</p>
              <p className="mt-2 text-xs text-slate-400">Sentiment {formatNumber(headline.sentiment, 3)}</p>
            </a>
          ))
        ) : (
          <p className="rounded-2xl bg-black/20 p-4 text-sm text-slate-400">No fresh headlines are available yet.</p>
        )}
      </div>
    </section>
  );
}

function HealthPanel({ evaluation }) {
  const rows = [
    ["Market", evaluation.market_health],
    ["Futures", evaluation.futures_health],
    ["News", evaluation.news_health]
  ];
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Refresh Health</h2>
      <div className="mt-5 space-y-3">
        {rows.map(([label, health]) => (
          <div key={label} className="rounded-2xl bg-black/20 p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{label}</span>
              <span className="rounded-full bg-white/10 px-3 py-1 text-xs">{health.status}</span>
            </div>
            <p className="mt-2 text-sm text-slate-400">Last success {formatTime(health.last_success_at)}</p>
            <p className="text-sm text-slate-400">Next refresh {formatTime(health.next_refresh_at)}</p>
            {health.detail ? <p className="mt-2 text-sm text-amber-200">{health.detail}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function MarketContextPanel({ marketContext }) {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Market Context</h2>
      {marketContext ? (
        <>
          <p className="mt-2 text-sm text-slate-400">{marketContext.reason}</p>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <MiniStat label="Volatility" value={marketContext.volatility_regime} />
            <MiniStat label="Structure" value={marketContext.structure_regime} />
            <MiniStat label="ATR percent" value={formatPct(marketContext.atr_percent)} />
            <MiniStat label="Realized vol" value={formatPct(marketContext.realized_volatility_percent)} />
            <MiniStat label="Band width" value={formatPct(marketContext.bollinger_width_percent)} />
            <MiniStat label="Range position" value={formatPct(marketContext.range_position_percent, 0)} />
          </div>
        </>
      ) : (
        <p className="mt-5 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">Waiting for completed candle history.</p>
      )}
    </section>
  );
}

function LoadingPanel() {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-10 text-center shadow-glow">
      <p className="text-xl font-semibold">Starting live dashboard...</p>
      <p className="mt-2 text-slate-400">The backend is connecting to market data and news feeds.</p>
    </section>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-100">{value}</p>
    </div>
  );
}

function MiniLine({ label, value }) {
  return (
    <p>
      <span className="text-slate-500">{label}</span>{" "}
      <span className="font-medium text-slate-100">{value}</span>
    </p>
  );
}

function connectionClass(connection) {
  if (connection === "live") return "bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.8)]";
  if (connection === "reconnecting") return "bg-amber-300";
  if (connection === "offline") return "bg-rose-400";
  return "bg-cyan-300";
}

function formatUsd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(Number(value));
}

function formatCompactUsd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const amount = Number(value);
  if (Math.abs(amount) >= 1_000_000_000) return `$${(amount / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(amount) >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000) return `$${(amount / 1_000).toFixed(2)}K`;
  return formatUsd(amount);
}

function formatPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}%`;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function formatRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${Number(value).toFixed(1)}x`;
}

function formatAgeSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const seconds = Math.max(0, Number(value));
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

function shakeoutSignalContext(shakeout, signal) {
  if (!shakeout) return "Waiting for context";
  if (shakeout.status === "CALM") return "Context only";
  const mainSignal = signal?.signal ?? "HOLD / NEUTRAL";
  const riskSide = shakeout.direction?.includes("UPSIDE")
    ? "BUY"
    : shakeout.direction?.includes("DOWNSIDE")
      ? "SELL"
      : null;
  if (!riskSide) return `Context only; two-sided while signal is ${mainSignal}`;
  if (mainSignal === "STRONG BUY" && riskSide === "BUY") {
    return "Context only; agrees with signal";
  }
  if (mainSignal === "STRONG SELL" && riskSide === "SELL") {
    return "Context only; agrees with signal";
  }
  if (mainSignal === "STRONG BUY" || mainSignal === "STRONG SELL") {
    return "Context only; conflicts with signal";
  }
  return "Context only; neutral signal";
}

function formatTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
