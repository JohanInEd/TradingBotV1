import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

const improvementIdeas = [
  {
    title: "Backtest the tri-factor weights",
    text: "Store every evaluation and compare 40/30/30 against walk-forward alternatives before changing thresholds."
  },
  {
    title: "Add volatility-aware risk",
    text: "Size paper futures from ATR or realized volatility instead of a fixed stop percentage."
  },
  {
    title: "Explain every signal",
    text: "Attach a short reason chain that names which timeframe, headline group, and macro condition moved the score."
  },
  {
    title: "Persist news and market state",
    text: "Save snapshots to SQLite so the dashboard can show history, outages, and signal drift after restarts."
  },
  {
    title: "Add alert channels",
    text: "Send only confirmed LONG/SHORT transitions to Telegram, Discord, or email with cooldown rules."
  }
];

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
            <section className="grid gap-4 lg:grid-cols-5">
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
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              <SignalPanel evaluation={evaluation} futures={futures} futuresMetrics={futuresMetrics} priceRange={priceRange} />
              <NewsPanel headlines={allHeadlines} />
            </section>

            <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
              <HealthPanel evaluation={evaluation} />
              <IdeasPanel />
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

function SignalPanel({ evaluation, futures, futuresMetrics, priceRange }) {
  const technical = evaluation.live_technical ?? evaluation.technical;
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

function IdeasPanel() {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Improvement Ideas</h2>
      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {improvementIdeas.map((idea) => (
          <article key={idea.title} className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <p className="font-medium text-cyan-100">{idea.title}</p>
            <p className="mt-2 text-sm text-slate-400">{idea.text}</p>
          </article>
        ))}
      </div>
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

function formatPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}%`;
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
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
