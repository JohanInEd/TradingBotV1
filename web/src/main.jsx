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
  const chart = snapshot?.chart;
  const market = evaluation?.market;
  const signal = evaluation?.signal;
  const sentiment = evaluation?.sentiment;
  const macro = evaluation?.macro;
  const futures = evaluation?.futures;
  const paperSetup = evaluation?.paper_setup;
  const futuresMetrics = evaluation?.futures_metrics;
  const priceRange = evaluation?.price_range;
  const probability = evaluation?.probability_forecast;
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
                label={`${probability?.horizon_hours ?? 24}h Backtest Odds`}
                value={`${formatProbability(probability?.up_probability)} up / ${formatProbability(probability?.down_probability)} down`}
                detail={`${probability?.confidence ?? "-"} - ${probability?.sample_size ?? 0}/${probability?.candidate_count ?? 0} similar samples`}
                tone={!probability ? "neutral" : probability.up_probability >= probability.down_probability ? "positive" : "negative"}
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

            <DecisionChart evaluation={evaluation} chart={chart} />

            <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              <SignalPanel evaluation={evaluation} futures={futures} paperSetup={paperSetup} futuresMetrics={futuresMetrics} probability={probability} priceRange={priceRange} shakeout={shakeout} />
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

function DecisionChart({ evaluation, chart }) {
  const candles = useMemo(
    () => (chart?.candles ?? []).filter((candle) => isFiniteNumber(candle.close)),
    [chart]
  );
  const technical = evaluation.live_technical ?? evaluation.technical;
  const decision = useMemo(() => buildDecision(evaluation), [evaluation]);

  if (!candles.length) {
    return (
      <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
        <h2 className="text-xl font-semibold">BTC Long / Short Map</h2>
        <p className="mt-4 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">
          Waiting for candle history before drawing the decision map.
        </p>
      </section>
    );
  }

  const latest = candles[candles.length - 1];
  const currentPrice = evaluation.market?.price ?? latest.close;
  const priceRange = evaluation.price_range;
  const futuresMetrics = evaluation.futures_metrics;
  const shakeout = evaluation.shakeout;

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">BTC Long / Short Map</h2>
          <p className="mt-1 text-sm text-slate-400">
            {chart?.timeframe ?? "4h"} candles with trend, momentum, volatility, volume, and futures pressure.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[30rem]">
          <DecisionGauge label="Long" value={decision.long} tone="positive" />
          <DecisionGauge label="Short" value={decision.short} tone="negative" />
          <DecisionGauge label="Flat" value={decision.flat} tone="neutral" />
        </div>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="rounded-2xl bg-black/20 p-4">
          <PriceDecisionSvg
            candles={candles}
            currentPrice={currentPrice}
            priceRange={priceRange}
            decision={decision}
          />
          <div className="mt-4 grid gap-2 text-xs text-slate-400 sm:grid-cols-3 lg:grid-cols-6">
            <LegendItem color="bg-emerald-300" label="EMA 20" />
            <LegendItem color="bg-cyan-300" label="EMA 50" />
            <LegendItem color="bg-amber-200" label="VWAP" />
            <LegendItem color="bg-violet-300" label="Bollinger" />
            <LegendItem color="bg-slate-300" label="Support / resistance" />
            <LegendItem color={decision.markerClass} label={decision.bias} />
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Current bias</p>
            <p className={`mt-2 text-3xl font-semibold ${decision.textClass}`}>{decision.bias}</p>
            <p className="mt-2 text-sm text-slate-300">{decision.reason}</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <MiniStat label="RSI 14" value={formatNumber(technical.rsi14, 1)} />
            <MiniStat label="ADX 14" value={formatNumber(latest.adx14, 1)} />
            <MiniStat label="MACD hist" value={formatNumber(technical.macd_histogram, 1)} />
            <MiniStat label="Score" value={formatNumber(evaluation.signal.score, 3)} />
          </div>
          <div className="rounded-2xl bg-black/20 p-4 text-sm text-slate-300">
            <MiniLine label="Live price" value={formatUsd(currentPrice)} />
            <MiniLine label="Support" value={formatUsd(priceRange?.support_level)} />
            <MiniLine label="Resistance" value={formatUsd(priceRange?.resistance_level)} />
            <MiniLine label="Funding" value={formatPct((futuresMetrics?.funding_rate ?? 0) * 100, 4)} />
            <MiniLine label="Open interest" value={formatCompactUsd(futuresMetrics?.open_interest_value)} />
            <MiniLine label="Long/short" value={formatNumber(futuresMetrics?.long_short_ratio, 2)} />
            <MiniLine label="Shakeout" value={`${shakeout?.status ?? "-"} ${shakeout?.direction ?? ""}`} />
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-4">
        <IndicatorPanel
          title="RSI"
          candles={candles}
          keys={["rsi14"]}
          domain={[0, 100]}
          guides={[30, 50, 70]}
          colors={["#67e8f9"]}
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="MACD"
          candles={candles}
          keys={["macd_histogram"]}
          domain="auto"
          colors={["#fbbf24"]}
          histogram
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="ADX"
          candles={candles}
          keys={["adx14"]}
          domain={[0, 60]}
          guides={[20, 25, 40]}
          colors={["#a78bfa"]}
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="Volume"
          candles={candles}
          keys={["volume"]}
          domain={[0, Math.max(...candles.map((candle) => candle.volume ?? 0), 1)]}
          colors={["#94a3b8"]}
          histogram
          formatter={(value) => formatCompact(value)}
        />
      </div>
    </section>
  );
}

function PriceDecisionSvg({ candles, currentPrice, priceRange, decision }) {
  const width = 980;
  const height = 410;
  const margin = { top: 18, right: 78, bottom: 34, left: 68 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const priceValues = candles.flatMap((candle) => [
    candle.high,
    candle.low,
    candle.ema20,
    candle.ema50,
    candle.vwap,
    candle.bollinger_high,
    candle.bollinger_low
  ]);
  priceValues.push(
    currentPrice,
    priceRange?.expected_low,
    priceRange?.expected_high,
    priceRange?.support_level,
    priceRange?.resistance_level
  );
  const [minPrice, maxPrice] = paddedDomain(priceValues, 0.08);
  const xFor = (index) => margin.left + (candles.length <= 1 ? 0 : (index / (candles.length - 1)) * innerWidth);
  const yFor = (value) => margin.top + ((maxPrice - value) / (maxPrice - minPrice || 1)) * innerHeight;
  const candleWidth = Math.max(3, Math.min(10, innerWidth / candles.length * 0.58));
  const lineKeys = [
    ["ema20", "#6ee7b7"],
    ["ema50", "#67e8f9"],
    ["vwap", "#fde68a"]
  ];
  const bollingerTop = seriesPath(candles, "bollinger_high", xFor, yFor);
  const bollingerBottom = seriesPath([...candles].reverse(), "bollinger_low", (index) => xFor(candles.length - 1 - index), yFor);
  const bandPath = bollingerTop && bollingerBottom ? `${bollingerTop} L ${bollingerBottom.slice(2)} Z` : "";
  const latestX = xFor(candles.length - 1);
  const markerY = yFor(currentPrice);
  const markerColor = decision.side === "LONG" ? "#34d399" : decision.side === "SHORT" ? "#fb7185" : "#67e8f9";

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full overflow-visible" role="img" aria-label="Bitcoin long short decision chart">
      <rect x="0" y="0" width={width} height={height} rx="18" fill="rgba(2,6,23,0.42)" />
      {[0.25, 0.5, 0.75].map((tick) => {
        const y = margin.top + tick * innerHeight;
        return <line key={tick} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="rgba(148,163,184,0.16)" />;
      })}

      {isFiniteNumber(priceRange?.expected_low) && isFiniteNumber(priceRange?.expected_high) ? (
        <rect
          x={margin.left}
          y={yFor(priceRange.expected_high)}
          width={innerWidth}
          height={Math.max(2, yFor(priceRange.expected_low) - yFor(priceRange.expected_high))}
          fill="rgba(34,211,238,0.07)"
        />
      ) : null}

      {bandPath ? <path d={bandPath} fill="rgba(167,139,250,0.12)" stroke="rgba(167,139,250,0.35)" strokeWidth="1" /> : null}

      {candles.map((candle, index) => {
        const x = xFor(index);
        const openY = yFor(candle.open ?? candle.close);
        const closeY = yFor(candle.close);
        const highY = yFor(candle.high ?? candle.close);
        const lowY = yFor(candle.low ?? candle.close);
        const bullish = candle.close >= (candle.open ?? candle.close);
        const bodyY = Math.min(openY, closeY);
        const bodyHeight = Math.max(2, Math.abs(openY - closeY));
        const color = bullish ? "#34d399" : "#fb7185";
        return (
          <g key={candle.time}>
            <line x1={x} x2={x} y1={highY} y2={lowY} stroke={color} strokeOpacity="0.78" />
            <rect
              x={x - candleWidth / 2}
              y={bodyY}
              width={candleWidth}
              height={bodyHeight}
              rx="1"
              fill={color}
              fillOpacity={bullish ? "0.72" : "0.64"}
            />
          </g>
        );
      })}

      {lineKeys.map(([key, color]) => {
        const path = seriesPath(candles, key, xFor, yFor);
        return path ? <path key={key} d={path} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" /> : null;
      })}

      {[
        ["Support", priceRange?.support_level, "rgba(226,232,240,0.55)"],
        ["Resistance", priceRange?.resistance_level, "rgba(226,232,240,0.55)"],
        ["Expected low", priceRange?.expected_low, "rgba(34,211,238,0.45)"],
        ["Expected high", priceRange?.expected_high, "rgba(34,211,238,0.45)"]
      ].map(([label, value, color]) => isFiniteNumber(value) ? (
        <g key={label}>
          <line x1={margin.left} x2={width - margin.right} y1={yFor(value)} y2={yFor(value)} stroke={color} strokeDasharray="6 6" />
          <text x={width - margin.right + 8} y={yFor(value) + 4} fill="rgb(203,213,225)" fontSize="11">{label}</text>
        </g>
      ) : null)}

      <line x1={margin.left} x2={width - margin.right} y1={markerY} y2={markerY} stroke={markerColor} strokeOpacity="0.65" />
      <DecisionMarker x={latestX} y={markerY} side={decision.side} color={markerColor} />
      <text x={latestX - 28} y={Math.max(18, markerY - 18)} fill={markerColor} fontSize="14" fontWeight="700">{decision.bias}</text>

      {[minPrice, (minPrice + maxPrice) / 2, maxPrice].map((value) => (
        <text key={value} x={width - margin.right + 8} y={yFor(value) + 4} fill="rgb(148,163,184)" fontSize="11">
          {formatUsd(value)}
        </text>
      ))}
      <text x={margin.left} y={height - 12} fill="rgb(148,163,184)" fontSize="11">
        {formatShortDate(candles[0]?.time)}
      </text>
      <text x={width - margin.right - 92} y={height - 12} fill="rgb(148,163,184)" fontSize="11">
        {formatShortDate(candles[candles.length - 1]?.time)}
      </text>
    </svg>
  );
}

function DecisionMarker({ x, y, side, color }) {
  if (side === "LONG") {
    return <path d={`M ${x} ${y - 14} L ${x - 12} ${y + 10} L ${x + 12} ${y + 10} Z`} fill={color} />;
  }
  if (side === "SHORT") {
    return <path d={`M ${x} ${y + 14} L ${x - 12} ${y - 10} L ${x + 12} ${y - 10} Z`} fill={color} />;
  }
  return <circle cx={x} cy={y} r="9" fill={color} />;
}

function IndicatorPanel({ title, candles, keys, domain, guides = [], colors, histogram = false, formatter }) {
  const width = 360;
  const height = 118;
  const margin = { top: 14, right: 34, bottom: 18, left: 38 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const values = candles.flatMap((candle) => keys.map((key) => candle[key])).filter(isFiniteNumber);
  const [minValue, maxValue] = Array.isArray(domain) ? domain : paddedDomain(values, 0.18);
  const xFor = (index) => margin.left + (candles.length <= 1 ? 0 : (index / (candles.length - 1)) * innerWidth);
  const yFor = (value) => margin.top + ((maxValue - value) / (maxValue - minValue || 1)) * innerHeight;
  const zeroY = yFor(Math.max(minValue, Math.min(maxValue, 0)));
  const barWidth = Math.max(2, innerWidth / candles.length * 0.6);

  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <p className="text-xs text-slate-400">{formatter(values[values.length - 1])}</p>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-2 h-auto w-full" role="img" aria-label={`${title} indicator`}>
        <rect x="0" y="0" width={width} height={height} rx="14" fill="rgba(2,6,23,0.36)" />
        {guides.map((guide) => (
          <line key={guide} x1={margin.left} x2={width - margin.right} y1={yFor(guide)} y2={yFor(guide)} stroke="rgba(148,163,184,0.22)" strokeDasharray="4 5" />
        ))}
        {histogram ? (
          candles.map((candle, index) => {
            const value = candle[keys[0]];
            if (!isFiniteNumber(value)) return null;
            const y = yFor(value);
            const fill = title === "MACD"
              ? value >= 0 ? "#34d399" : "#fb7185"
              : colors[0];
            return (
              <rect
                key={`${candle.time}-${index}`}
                x={xFor(index) - barWidth / 2}
                y={Math.min(y, zeroY)}
                width={barWidth}
                height={Math.max(1, Math.abs(y - zeroY))}
                fill={fill}
                fillOpacity="0.75"
              />
            );
          })
        ) : keys.map((key, index) => {
          const path = seriesPath(candles, key, xFor, yFor);
          return path ? <path key={key} d={path} fill="none" stroke={colors[index]} strokeWidth="2.5" strokeLinecap="round" /> : null;
        })}
      </svg>
    </div>
  );
}

function DecisionGauge({ label, value, tone }) {
  const color = {
    positive: "bg-emerald-300 text-emerald-100",
    negative: "bg-rose-300 text-rose-100",
    neutral: "bg-cyan-300 text-cyan-100"
  }[tone];
  return (
    <div className="rounded-2xl bg-black/20 p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-400">{label}</span>
        <span className={color.split(" ")[1]}>{value.toFixed(0)}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full ${color.split(" ")[0]}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function LegendItem({ color, label }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      <span>{label}</span>
    </div>
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

function SignalPanel({ evaluation, futures, paperSetup, futuresMetrics, probability, priceRange, shakeout }) {
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
        <PaperSetupCard paperSetup={paperSetup} futures={futures} />
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

      {probability ? (
        <div className="mt-4 rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-sm font-medium text-emerald-100">
                Historical probability for next {probability.horizon_hours}h
              </p>
              <p className="mt-2 text-sm text-slate-300">
                Similar closed 4h setups moved up {formatProbability(probability.up_probability)}
                {" "}and down {formatProbability(probability.down_probability)} by horizon close.
              </p>
              <p className="mt-2 text-xs text-slate-400">{probability.method}</p>
            </div>
            <div className="min-w-64 rounded-xl bg-black/20 p-3 text-sm text-slate-300">
              <MiniLine label="Long TP / SL" value={`${formatProbability(probability.long_tp_before_sl_probability)} / ${formatProbability(probability.long_sl_before_tp_probability)}`} />
              <MiniLine label="Short TP / SL" value={`${formatProbability(probability.short_tp_before_sl_probability)} / ${formatProbability(probability.short_sl_before_tp_probability)}`} />
              <MiniLine label="Expected R" value={`L ${formatNumber(probability.expected_long_r, 2)} / S ${formatNumber(probability.expected_short_r, 2)}`} />
              <MiniLine label="Avg move" value={formatPct(probability.average_forward_return_percent)} />
              <MiniLine label="Samples" value={`${probability.sample_size}/${probability.candidate_count}`} />
              <MiniLine label="Confidence" value={probability.confidence} />
            </div>
          </div>
        </div>
      ) : null}

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

function PaperSetupCard({ paperSetup, futures }) {
  if (!paperSetup) {
    return (
      <div className="rounded-2xl bg-black/20 p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-slate-200">paper setup</p>
          <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">no order placed</span>
        </div>
        <p className="mt-2 text-3xl font-semibold text-cyan-200">{futures?.action ?? "STAY FLAT"}</p>
        <p className="mt-2 text-sm text-slate-400">
          {futures?.reason ?? "No closed-candle paper setup."}
        </p>
        <p className="mt-3 text-xs text-slate-500">
          No paper setup for this closed candle. No order placed. Not financial advice.
        </p>
      </div>
    );
  }

  const sideClass = paperSetup.side === "LONG" ? "text-emerald-200" : "text-rose-200";
  const borderClass = paperSetup.side === "LONG" ? "border-emerald-300/25" : "border-rose-300/25";

  return (
    <div className={`rounded-2xl border ${borderClass} bg-black/20 p-4`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">paper setup</p>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">no order placed</span>
      </div>
      <p className={`mt-2 text-3xl font-semibold ${sideClass}`}>{paperSetup.action}</p>
      <p className="mt-2 text-sm text-slate-400">
        Closed candle {formatShortDate(paperSetup.candle_time)} - {paperSetup.disclaimer}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300">
        <MiniLine label="Entry" value={formatUsd(paperSetup.entry_price)} />
        <MiniLine label="Stop loss" value={formatUsd(paperSetup.stop_loss)} />
        <MiniLine label="Take profit" value={formatUsd(paperSetup.take_profit)} />
        <MiniLine label="Reward/risk" value={`${formatNumber(paperSetup.reward_to_risk, 2)}R`} />
        <MiniLine label="Max loss" value={formatUsd(paperSetup.max_loss)} />
        <p className="col-span-2">
          <span className="text-slate-500">Position est.</span>{" "}
          <span className="font-medium text-slate-100">{paperSetup.position_estimate}</span>
        </p>
      </div>
    </div>
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

function buildDecision(evaluation) {
  const score = Number(evaluation.signal?.score ?? 0);
  const signal = evaluation.signal?.signal ?? "HOLD / NEUTRAL";
  const action = evaluation.futures?.action ?? "STAY FLAT";
  const probability = evaluation.probability_forecast;
  const side = action === "GO LONG" || signal === "STRONG BUY"
    ? "LONG"
    : action === "GO SHORT" || signal === "STRONG SELL"
      ? "SHORT"
      : "FLAT";
  let long;
  let short;
  let flat;

  if (probability) {
    long = probability.up_probability * 100;
    short = probability.down_probability * 100;
    flat = probability.flat_probability * 100;
  } else {
    const directional = Math.min(96, Math.abs(score) * 100);
    long = score > 0 ? directional : Math.max(0, 12 + score * 30);
    short = score < 0 ? directional : Math.max(0, 12 - score * 30);
    flat = Math.max(0, 100 - long - short);

    if (side === "LONG") {
      long = Math.max(long, 58);
      flat = Math.min(flat, 34);
    } else if (side === "SHORT") {
      short = Math.max(short, 58);
      flat = Math.min(flat, 34);
    } else {
      flat = Math.max(flat, 62);
    }
  }

  const total = long + short + flat || 1;
  long = (long / total) * 100;
  short = (short / total) * 100;
  flat = (flat / total) * 100;

  const bias = side === "LONG" ? "GO LONG" : side === "SHORT" ? "GO SHORT" : "STAY FLAT";
  return {
    side,
    bias,
    long,
    short,
    flat,
    reason: probability
      ? `${probability.horizon_hours}h historical odds from ${probability.sample_size} similar closed-candle setups.`
      : evaluation.futures?.reason ?? "Waiting for full confirmation.",
    textClass: side === "LONG" ? "text-emerald-300" : side === "SHORT" ? "text-rose-300" : "text-cyan-200",
    markerClass: side === "LONG" ? "bg-emerald-300" : side === "SHORT" ? "bg-rose-300" : "bg-cyan-300"
  };
}

function paddedDomain(values, padding = 0.1) {
  const finite = values.filter(isFiniteNumber);
  if (!finite.length) return [0, 1];
  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (min === max) {
    min -= Math.max(1, Math.abs(min) * 0.01);
    max += Math.max(1, Math.abs(max) * 0.01);
  }
  const pad = (max - min) * padding;
  return [min - pad, max + pad];
}

function seriesPath(rows, key, xFor, yFor) {
  const points = rows
    .map((row, index) => [xFor(index), row[key]])
    .filter(([, value]) => isFiniteNumber(value));
  if (!points.length) return "";
  return points
    .map(([x, value], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${yFor(value).toFixed(2)}`)
    .join(" ");
}

function isFiniteNumber(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value));
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

function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const amount = Number(value);
  if (Math.abs(amount) >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(amount) >= 1_000_000) return `${(amount / 1_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000) return `${(amount / 1_000).toFixed(2)}K`;
  return amount.toFixed(2);
}

function formatPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}%`;
}

function formatProbability(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(0)}%`;
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

function formatShortDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit"
  }).format(new Date(value));
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
