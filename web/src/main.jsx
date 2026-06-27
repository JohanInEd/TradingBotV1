import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [connection, setConnection] = useState("connecting");
  const [error, setError] = useState(null);
  const [selectedTradeMode, setSelectedTradeMode] = useState("4h");
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
  const tradeFilter = evaluation?.trade_filter;
  const paperJournal = snapshot?.paper_journal;
  const scanner = evaluation?.scanner;
  const confidence = snapshot?.confidence;
  const simulator = snapshot?.simulator;
  const tradeModes = snapshot?.trade_modes;

  useEffect(() => {
    const modes = tradeModes?.modes;
    if (!modes || modes[selectedTradeMode]) return;
    const fallback = tradeModes?.selected ?? Object.keys(modes)[0] ?? "4h";
    setSelectedTradeMode(fallback);
  }, [tradeModes, selectedTradeMode]);

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
                label="Confidence"
                value={`${formatNumber(confidence?.percent, 1)}% ${confidence?.label ?? ""}`}
                detail={confidence?.action ? `${confidence.action} - ${confidence.summary}` : "Waiting for confidence context"}
                tone={confidenceTone(confidence)}
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
                detail={`Weighted ${formatNumber(sentiment.score, 3)} - ${(sentiment.sources ?? []).length} sources - ${evaluation.news_health.status}`}
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
              <MetricCard
                label="Trade Filter"
                value={tradeFilter?.status ?? "WAITING"}
                detail={tradeFilter?.reasons?.[0] ?? "Risk gates not evaluated yet"}
                tone={tradeFilterTone(tradeFilter)}
              />
            </section>

            <DecisionChart
              evaluation={evaluation}
              chart={chart}
              tradeModes={tradeModes}
              selectedTimeframe={selectedTradeMode}
              onSelectTimeframe={setSelectedTradeMode}
            />

            <ScannerPanel scanner={scanner} />

            <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
              <ConfidencePanel confidence={confidence} />
              <SimulatorPanel simulator={simulator} />
            </section>

            <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              <SignalPanel evaluation={evaluation} futures={futures} paperSetup={paperSetup} futuresMetrics={futuresMetrics} probability={probability} priceRange={priceRange} shakeout={shakeout} tradeFilter={tradeFilter} />
              <NewsPanel
                headlines={allHeadlines}
                sources={sentiment?.sources ?? []}
                events={sentiment?.events ?? []}
                macro={macro}
              />
            </section>

            <PaperJournalPanel report={paperJournal} />

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

function DecisionChart({ evaluation, chart, tradeModes, selectedTimeframe, onSelectTimeframe }) {
  const modeOptions = tradeModes?.options ?? [
    { timeframe: "4h", label: "4h Trade" },
    { timeframe: "1h", label: "1h Trade" },
    { timeframe: "30m", label: "30min Trade" }
  ];
  const modeMap = tradeModes?.modes ?? {};
  const activeTimeframe = modeMap[selectedTimeframe]
    ? selectedTimeframe
    : tradeModes?.selected ?? chart?.timeframe ?? "4h";
  const activeMode = modeMap[activeTimeframe];
  const activeChart = activeMode?.chart ?? chart;
  const modeEvaluation = activeMode?.available
    ? {
        ...evaluation,
        technical: activeMode.technical ?? evaluation.technical,
        live_technical: activeMode.technical ?? evaluation.live_technical,
        signal: activeMode.signal ?? evaluation.signal,
        futures: activeMode.futures ?? evaluation.futures,
        trade_filter: activeMode.trade_filter ?? evaluation.trade_filter,
        paper_setup: activeMode.paper_setup ?? null,
        price_range: activeMode.price_range ?? null,
        probability_forecast: activeMode.probability_forecast ?? null,
        scenario_forecast: activeMode.scenario_forecast ?? null,
        market_context: activeMode.market_context ?? null
      }
    : evaluation;
  const candles = useMemo(
    () => (activeChart?.candles ?? []).filter((candle) => isFiniteNumber(candle.close)),
    [activeChart]
  );
  const [rangeKey, setRangeKey] = useState("7D");
  const [panOffset, setPanOffset] = useState(0);
  const [overlays, setOverlays] = useState({
    ema: true,
    vwap: true,
    bollinger: true,
    levels: true,
    scenario: true,
    setup: true,
    zones: true,
    ribbon: true
  });
  const technical = modeEvaluation.live_technical ?? modeEvaluation.technical;
  const decision = useMemo(() => buildDecision(modeEvaluation), [modeEvaluation]);
  const scenarioForecast = modeEvaluation.scenario_forecast;

  if (!candles.length) {
    return (
      <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="text-xl font-semibold">BTC Long / Short Map</h2>
          <TradeModeSelector
            options={modeOptions}
            activeTimeframe={activeTimeframe}
            modes={modeMap}
            onSelect={onSelectTimeframe}
          />
        </div>
        <p className="mt-4 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">
          Waiting for candle history before drawing the decision map.
        </p>
      </section>
    );
  }

  const latest = candles[candles.length - 1];
  const currentPrice = evaluation.market?.price ?? latest.close;
  const priceRange = modeEvaluation.price_range;
  const futuresMetrics = evaluation.futures_metrics;
  const shakeout = evaluation.shakeout;
  const paperSetup = modeEvaluation.paper_setup;
  const tradeFilter = modeEvaluation.trade_filter;
  const probability = modeEvaluation.probability_forecast;
  const marketContext = modeEvaluation.market_context;
  const candlesPerDay = candlesPerDayFor(activeChart?.timeframe ?? activeTimeframe);
  const rangeOptions = [
    ["1D", candlesPerDay],
    ["3D", candlesPerDay * 3],
    ["7D", candlesPerDay * 7],
    ["14D", candlesPerDay * 14],
    ["30D", candlesPerDay * 30],
    ["All", candles.length]
  ];
  const visibleCount = Math.min(candles.length, rangeOptions.find(([key]) => key === rangeKey)?.[1] ?? 42);
  const maxOffset = Math.max(0, candles.length - visibleCount);
  const normalizedOffset = Math.min(maxOffset, Math.max(0, panOffset));
  const startIndex = Math.max(0, candles.length - visibleCount - normalizedOffset);
  const visibleCandles = candles.slice(startIndex, startIndex + visibleCount);
  const setZoomRange = (key) => {
    setRangeKey(key);
    setPanOffset(0);
  };
  const panByCandles = (delta) => {
    setPanOffset((value) => Math.min(maxOffset, Math.max(0, value + delta)));
  };
  const toggleOverlay = (key) => {
    setOverlays((value) => ({ ...value, [key]: !value[key] }));
  };

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">BTC Long / Short Map</h2>
          <p className="mt-1 text-sm text-slate-400">
            {activeChart?.timeframe ?? "4h"} candles with independent trend, momentum, volatility, probability, and paper setup context.
          </p>
        </div>
        <div className="flex flex-col gap-3 lg:min-w-[36rem]">
          <TradeModeSelector
            options={modeOptions}
            activeTimeframe={activeTimeframe}
            modes={modeMap}
            onSelect={onSelectTimeframe}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <DecisionGauge label="Long" value={decision.long} tone="positive" />
            <DecisionGauge label="Short" value={decision.short} tone="negative" />
            <DecisionGauge label="Flat" value={decision.flat} tone="neutral" />
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_21rem]">
        <div className="rounded-2xl bg-black/20 p-4">
          <div className="mb-4 flex flex-col gap-3 2xl:flex-row 2xl:items-center 2xl:justify-between">
            <div className="flex flex-wrap gap-2">
              {rangeOptions.map(([key]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setZoomRange(key)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${rangeKey === key ? "border-cyan-300/60 bg-cyan-300/15 text-cyan-100" : "border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/40"}`}
                >
                  {key}
                </button>
              ))}
              <button
                type="button"
                onClick={() => panByCandles(Math.max(4, Math.floor(visibleCount / 3)))}
                className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300 hover:border-cyan-300/40"
              >
                Older
              </button>
              <button
                type="button"
                onClick={() => panByCandles(-Math.max(4, Math.floor(visibleCount / 3)))}
                className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300 hover:border-cyan-300/40"
              >
                Newer
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                ["ema", "EMA"],
                ["vwap", "VWAP"],
                ["bollinger", "Bands"],
                ["levels", "Levels"],
                ["scenario", "Scenario"],
                ["setup", "Setup"],
                ["zones", "Zones"],
                ["ribbon", "Trend"]
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleOverlay(key)}
                  className={`rounded-lg border px-3 py-2 text-xs font-medium transition ${overlays[key] ? "border-slate-300/30 bg-slate-300/10 text-slate-100" : "border-white/10 bg-transparent text-slate-500"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <PriceDecisionSvg
            candles={visibleCandles}
            allCandles={candles}
            visibleStartIndex={startIndex}
            visibleCount={visibleCount}
            onPan={panByCandles}
            currentPrice={currentPrice}
            priceRange={priceRange}
            decision={decision}
            scenarioForecast={scenarioForecast}
            paperSetup={paperSetup}
            overlays={overlays}
          />
          <div className="mt-4 grid gap-2 text-xs text-slate-400 sm:grid-cols-3 lg:grid-cols-7">
            <LegendItem color="bg-emerald-300" label="EMA 20" />
            <LegendItem color="bg-cyan-300" label="EMA 50" />
            <LegendItem color="bg-amber-200" label="VWAP" />
            <LegendItem color="bg-violet-300" label="Bollinger" />
            <LegendItem color="bg-slate-300" label="Support / resistance" />
            <LegendItem color={decision.markerClass} label={decision.bias} />
            <LegendItem color="bg-slate-400" label="7d scenario" />
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Current bias</p>
            <p className={`mt-2 text-3xl font-semibold ${decision.textClass}`}>{decision.bias}</p>
            <p className="mt-2 text-sm text-slate-300">{decision.reason}</p>
          </div>
          <ScenarioMapCard forecast={scenarioForecast} />
          <div className="grid grid-cols-2 gap-3">
            <MiniStat label="RSI 14" value={formatNumber(technical.rsi14, 1)} />
            <MiniStat label="ADX 14" value={formatNumber(visibleCandles[visibleCandles.length - 1]?.adx14 ?? latest.adx14, 1)} />
            <MiniStat label="MACD hist" value={formatNumber(technical.macd_histogram, 1)} />
            <MiniStat label="Score" value={formatNumber(modeEvaluation.signal.score, 3)} />
          </div>
          <div className="rounded-2xl bg-black/20 p-4 text-sm text-slate-300">
            <MiniLine label={`${activeChart?.timeframe ?? activeTimeframe} signal`} value={modeEvaluation.signal?.signal ?? "-"} />
            <MiniLine label="Trade filter" value={tradeFilter?.status ?? "-"} />
            <MiniLine label="Backtest odds" value={probability ? `${formatProbability(probability.up_probability)} up / ${formatProbability(probability.down_probability)} down` : "-"} />
            <MiniLine label="Expected R" value={probability ? `L ${formatNumber(probability.expected_long_r, 2)} / S ${formatNumber(probability.expected_short_r, 2)}` : "-"} />
            <MiniLine label="ATR" value={formatPct(marketContext?.atr_percent)} />
            <MiniLine label="Range position" value={formatPct(marketContext?.range_position_percent, 0)} />
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
          candles={visibleCandles}
          keys={["rsi14"]}
          domain={[0, 100]}
          guides={[30, 50, 70]}
          colors={["#67e8f9"]}
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="MACD"
          candles={visibleCandles}
          keys={["macd_histogram"]}
          domain="auto"
          colors={["#fbbf24"]}
          histogram
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="ADX"
          candles={visibleCandles}
          keys={["adx14"]}
          domain={[0, 60]}
          guides={[20, 25, 40]}
          colors={["#a78bfa"]}
          formatter={(value) => formatNumber(value, 0)}
        />
        <IndicatorPanel
          title="Volume"
          candles={visibleCandles}
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

function TradeModeSelector({ options, activeTimeframe, modes, onSelect }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const available = modes?.[option.timeframe]?.available !== false;
        const active = activeTimeframe === option.timeframe;
        return (
          <button
            key={option.timeframe}
            type="button"
            onClick={() => onSelect(option.timeframe)}
            className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
              active
                ? "border-emerald-300/60 bg-emerald-300/15 text-emerald-100"
                : "border-white/10 bg-white/5 text-slate-300 hover:border-emerald-300/40"
            } ${available ? "" : "opacity-60"}`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function PriceDecisionSvg({
  candles,
  allCandles,
  visibleStartIndex,
  visibleCount,
  onPan,
  currentPrice,
  priceRange,
  decision,
  scenarioForecast,
  paperSetup,
  overlays
}) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const [dragStart, setDragStart] = useState(null);
  const width = 980;
  const height = overlays.ribbon ? 446 : 410;
  const margin = { top: 18, right: 78, bottom: overlays.ribbon ? 70 : 34, left: 68 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const scenarioMedian = (scenarioForecast?.median_path ?? []).filter((point) => isFiniteNumber(point.price));
  const scenarioLower = (scenarioForecast?.lower_band_path ?? []).filter((point) => isFiniteNumber(point.price));
  const scenarioUpper = (scenarioForecast?.upper_band_path ?? []).filter((point) => isFiniteNumber(point.price));
  const scenarioPointCount = overlays.scenario ? Math.max(scenarioMedian.length, scenarioLower.length, scenarioUpper.length) : 0;
  const priceValues = candles.flatMap((candle) => [
    candle.high,
    candle.low,
    overlays.ema ? candle.ema20 : null,
    overlays.ema ? candle.ema50 : null,
    overlays.vwap ? candle.vwap : null,
    overlays.bollinger ? candle.bollinger_high : null,
    overlays.bollinger ? candle.bollinger_low : null
  ]);
  priceValues.push(
    currentPrice,
    overlays.levels ? priceRange?.expected_low : null,
    overlays.levels ? priceRange?.expected_high : null,
    overlays.levels ? priceRange?.support_level : null,
    overlays.levels ? priceRange?.resistance_level : null,
    overlays.scenario ? scenarioForecast?.expected_low : null,
    overlays.scenario ? scenarioForecast?.expected_high : null,
    overlays.setup ? paperSetup?.entry_price : null,
    overlays.setup ? paperSetup?.stop_loss : null,
    overlays.setup ? paperSetup?.take_profit : null,
    ...(overlays.scenario ? scenarioMedian.map((point) => point.price) : []),
    ...(overlays.scenario ? scenarioLower.map((point) => point.price) : []),
    ...(overlays.scenario ? scenarioUpper.map((point) => point.price) : [])
  );
  const [minPrice, maxPrice] = paddedDomain(priceValues, 0.08);
  const totalLastIndex = Math.max(candles.length - 1 + scenarioPointCount, candles.length - 1, 1);
  const xFor = (index) => margin.left + (index / totalLastIndex) * innerWidth;
  const scenarioXFor = (index) => xFor(candles.length - 1 + index);
  const yFor = (value) => margin.top + ((maxPrice - value) / (maxPrice - minPrice || 1)) * innerHeight;
  const candleWidth = Math.max(3, Math.min(10, innerWidth / candles.length * 0.58));
  const lineKeys = [
    ["ema20", "#6ee7b7"],
    ["ema50", "#67e8f9"],
    ["vwap", "#fde68a"]
  ].filter(([key]) => (key === "vwap" ? overlays.vwap : overlays.ema));
  const bollingerTop = overlays.bollinger ? seriesPath(candles, "bollinger_high", xFor, yFor) : "";
  const bollingerBottom = overlays.bollinger ? seriesPath([...candles].reverse(), "bollinger_low", (index) => xFor(candles.length - 1 - index), yFor) : "";
  const bandPath = bollingerTop && bollingerBottom ? `${bollingerTop} L ${bollingerBottom.slice(2)} Z` : "";
  const latestX = xFor(candles.length - 1);
  const markerY = yFor(currentPrice);
  const markerColor = decision.side === "LONG" ? "#34d399" : decision.side === "SHORT" ? "#fb7185" : "#67e8f9";
  const scenarioMedianPoints = overlays.scenario && scenarioMedian.length ? [{ price: currentPrice }, ...scenarioMedian] : [];
  const scenarioLowerPoints = overlays.scenario && scenarioLower.length ? [{ price: currentPrice }, ...scenarioLower] : [];
  const scenarioUpperPoints = overlays.scenario && scenarioUpper.length ? [{ price: currentPrice }, ...scenarioUpper] : [];
  const scenarioUpperPath = pathFromPoints(scenarioUpperPoints, scenarioXFor, yFor);
  const scenarioLowerPath = pathFromPoints(
    [...scenarioLowerPoints].reverse(),
    (index) => scenarioXFor(scenarioLowerPoints.length - 1 - index),
    yFor
  );
  const scenarioBandPath = scenarioUpperPath && scenarioLowerPath ? `${scenarioUpperPath} L ${scenarioLowerPath.slice(2)} Z` : "";
  const scenarioMedianPath = pathFromPoints(scenarioMedianPoints, scenarioXFor, yFor);
  const scenarioLabelPoint = scenarioMedian[scenarioMedian.length - 1];
  const scenarioLabelX = Math.min(width - margin.right - 82, scenarioXFor(scenarioMedianPoints.length - 1) + 8);
  const scenarioLabelY = scenarioLabelPoint
    ? Math.max(22, Math.min(height - 54, yFor(scenarioLabelPoint.price) - 10))
    : 0;
  const hoverCandle = hoverIndex === null ? null : candles[hoverIndex];
  const hoverX = hoverIndex === null ? null : xFor(hoverIndex);
  const trendRibbonY = height - 48;
  const trendRibbonHeight = 13;
  const candleStep = candles.length <= 1 ? innerWidth : innerWidth / (candles.length - 1);
  const longZoneTop = isFiniteNumber(priceRange?.support_level)
    ? yFor(priceRange.support_level * 1.006)
    : null;
  const longZoneBottom = isFiniteNumber(priceRange?.support_level)
    ? yFor(priceRange.support_level * 0.994)
    : null;
  const shortZoneTop = isFiniteNumber(priceRange?.resistance_level)
    ? yFor(priceRange.resistance_level * 1.006)
    : null;
  const shortZoneBottom = isFiniteNumber(priceRange?.resistance_level)
    ? yFor(priceRange.resistance_level * 0.994)
    : null;

  function pointerToIndex(event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = Math.max(0, Math.min(1, (x - margin.left) / innerWidth));
    return Math.max(0, Math.min(candles.length - 1, Math.round(ratio * Math.max(1, candles.length - 1))));
  }

  function handlePointerMove(event) {
    const nextIndex = pointerToIndex(event);
    setHoverIndex(nextIndex);
    if (dragStart) {
      const delta = nextIndex - dragStart.index;
      const threshold = Math.max(2, Math.floor(visibleCount / 24));
      if (Math.abs(delta) >= threshold) {
        onPan(-delta);
        setDragStart({ index: nextIndex });
      }
    }
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-auto w-full cursor-crosshair select-none overflow-visible"
      role="img"
      aria-label="Bitcoin long short decision chart"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragStart({ index: pointerToIndex(event) });
      }}
      onPointerMove={handlePointerMove}
      onPointerUp={(event) => {
        event.currentTarget.releasePointerCapture(event.pointerId);
        setDragStart(null);
      }}
      onPointerLeave={() => {
        setHoverIndex(null);
        setDragStart(null);
      }}
    >
      <rect x="0" y="0" width={width} height={height} rx="18" fill="rgba(2,6,23,0.42)" />
      {[0.25, 0.5, 0.75].map((tick) => {
        const y = margin.top + tick * innerHeight;
        return <line key={tick} x1={margin.left} x2={width - margin.right} y1={y} y2={y} stroke="rgba(148,163,184,0.16)" />;
      })}

      {overlays.zones && longZoneTop !== null && longZoneBottom !== null ? (
        <rect
          x={margin.left}
          y={Math.min(longZoneTop, longZoneBottom)}
          width={innerWidth}
          height={Math.max(2, Math.abs(longZoneBottom - longZoneTop))}
          fill="rgba(52,211,153,0.08)"
          stroke="rgba(52,211,153,0.18)"
        />
      ) : null}
      {overlays.zones && shortZoneTop !== null && shortZoneBottom !== null ? (
        <rect
          x={margin.left}
          y={Math.min(shortZoneTop, shortZoneBottom)}
          width={innerWidth}
          height={Math.max(2, Math.abs(shortZoneBottom - shortZoneTop))}
          fill="rgba(251,113,133,0.08)"
          stroke="rgba(251,113,133,0.18)"
        />
      ) : null}

      {overlays.levels && isFiniteNumber(priceRange?.expected_low) && isFiniteNumber(priceRange?.expected_high) ? (
        <rect
          x={margin.left}
          y={yFor(priceRange.expected_high)}
          width={innerWidth}
          height={Math.max(2, yFor(priceRange.expected_low) - yFor(priceRange.expected_high))}
          fill="rgba(34,211,238,0.07)"
        />
      ) : null}

      {bandPath ? <path d={bandPath} fill="rgba(167,139,250,0.12)" stroke="rgba(167,139,250,0.35)" strokeWidth="1" /> : null}
      {scenarioBandPath ? <path d={scenarioBandPath} fill="rgba(148,163,184,0.14)" stroke="rgba(148,163,184,0.24)" strokeWidth="1" /> : null}

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

      {scenarioMedianPath ? (
        <path d={scenarioMedianPath} fill="none" stroke="rgba(203,213,225,0.88)" strokeWidth="2.2" strokeDasharray="7 6" strokeLinecap="round" />
      ) : null}
      {scenarioMedianPath ? (
        <line x1={latestX} x2={latestX} y1={margin.top} y2={height - margin.bottom} stroke="rgba(203,213,225,0.22)" strokeDasharray="5 7" />
      ) : null}
      {scenarioLabelPoint ? (
        <g>
          <text x={scenarioLabelX} y={scenarioLabelY} fill="rgb(203,213,225)" fontSize="12" fontWeight="700">7d scenario</text>
          <text x={scenarioLabelX} y={scenarioLabelY + 15} fill="rgb(148,163,184)" fontSize="10">historical, not a prediction</text>
        </g>
      ) : null}

      {overlays.setup && paperSetup ? (
        <g>
          {[
            ["Entry", paperSetup.entry_price, "rgba(34,211,238,0.82)"],
            ["Stop", paperSetup.stop_loss, "rgba(251,113,133,0.82)"],
            ["Take profit", paperSetup.take_profit, "rgba(52,211,153,0.82)"]
          ].map(([label, value, color]) => isFiniteNumber(value) ? (
            <g key={label}>
              <line x1={margin.left} x2={width - margin.right} y1={yFor(value)} y2={yFor(value)} stroke={color} strokeWidth="1.5" strokeDasharray={label === "Entry" ? "none" : "8 5"} />
              <text x={margin.left + 8} y={yFor(value) - 5} fill={color} fontSize="11" fontWeight="700">{label}</text>
            </g>
          ) : null)}
          {isFiniteNumber(paperSetup.entry_price) && isFiniteNumber(paperSetup.stop_loss) && isFiniteNumber(paperSetup.take_profit) ? (
            <>
              <rect
                x={latestX + 8}
                y={Math.min(yFor(paperSetup.entry_price), yFor(paperSetup.take_profit))}
                width={46}
                height={Math.abs(yFor(paperSetup.entry_price) - yFor(paperSetup.take_profit))}
                fill="rgba(52,211,153,0.12)"
              />
              <rect
                x={latestX + 8}
                y={Math.min(yFor(paperSetup.entry_price), yFor(paperSetup.stop_loss))}
                width={46}
                height={Math.abs(yFor(paperSetup.entry_price) - yFor(paperSetup.stop_loss))}
                fill="rgba(251,113,133,0.12)"
              />
            </>
          ) : null}
        </g>
      ) : null}

      {overlays.levels ? [
        ["Support", priceRange?.support_level, "rgba(226,232,240,0.55)"],
        ["Resistance", priceRange?.resistance_level, "rgba(226,232,240,0.55)"],
        ["Expected low", priceRange?.expected_low, "rgba(34,211,238,0.45)"],
        ["Expected high", priceRange?.expected_high, "rgba(34,211,238,0.45)"]
      ].map(([label, value, color]) => isFiniteNumber(value) ? (
        <g key={label}>
          <line x1={margin.left} x2={width - margin.right} y1={yFor(value)} y2={yFor(value)} stroke={color} strokeDasharray="6 6" />
          <text x={width - margin.right + 8} y={yFor(value) + 4} fill="rgb(203,213,225)" fontSize="11">{label}</text>
        </g>
      ) : null) : null}

      <line x1={margin.left} x2={width - margin.right} y1={markerY} y2={markerY} stroke={markerColor} strokeOpacity="0.65" />
      <DecisionMarker x={latestX} y={markerY} side={decision.side} color={markerColor} />
      <text x={latestX - 28} y={Math.max(18, markerY - 18)} fill={markerColor} fontSize="14" fontWeight="700">{decision.bias}</text>

      {overlays.ribbon ? (
        <g>
          <text x={margin.left} y={trendRibbonY - 8} fill="rgb(148,163,184)" fontSize="11">Trend</text>
          {candles.map((candle, index) => {
            const trend = trendState(candle);
            const fill = trend === "up" ? "rgba(52,211,153,0.78)" : trend === "down" ? "rgba(251,113,133,0.72)" : "rgba(103,232,249,0.45)";
            return (
              <rect
                key={`${candle.time}-trend`}
                x={xFor(index) - candleStep / 2}
                y={trendRibbonY}
                width={Math.max(2, candleStep)}
                height={trendRibbonHeight}
                fill={fill}
              />
            );
          })}
        </g>
      ) : null}

      {hoverCandle && hoverX !== null ? (
        <g pointerEvents="none">
          <line x1={hoverX} x2={hoverX} y1={margin.top} y2={height - margin.bottom} stroke="rgba(226,232,240,0.35)" strokeDasharray="4 6" />
          <circle cx={hoverX} cy={yFor(hoverCandle.close)} r="4" fill="rgb(226,232,240)" />
          <rect
            x={hoverX > width * 0.64 ? margin.left + 12 : hoverX + 14}
            y={margin.top + 10}
            width="216"
            height="150"
            rx="12"
            fill="rgba(15,23,42,0.94)"
            stroke="rgba(148,163,184,0.28)"
          />
          {[
            formatShortDate(hoverCandle.time),
            `O ${formatUsd(hoverCandle.open)} H ${formatUsd(hoverCandle.high)}`,
            `L ${formatUsd(hoverCandle.low)} C ${formatUsd(hoverCandle.close)}`,
            `Vol ${formatCompact(hoverCandle.volume)}`,
            `RSI ${formatNumber(hoverCandle.rsi14, 1)}  MACD ${formatNumber(hoverCandle.macd_histogram, 1)}`,
            `EMA ${formatUsd(hoverCandle.ema20)} / ${formatUsd(hoverCandle.ema50)}`,
            `ADX ${formatNumber(hoverCandle.adx14, 1)}  ${trendLabel(hoverCandle)}`
          ].map((line, index) => (
            <text
              key={line}
              x={(hoverX > width * 0.64 ? margin.left + 28 : hoverX + 30)}
              y={margin.top + 34 + index * 18}
              fill={index === 0 ? "rgb(226,232,240)" : "rgb(203,213,225)"}
              fontSize={index === 0 ? "12" : "11"}
              fontWeight={index === 0 ? "700" : "500"}
            >
              {line}
            </text>
          ))}
        </g>
      ) : null}

      {[minPrice, (minPrice + maxPrice) / 2, maxPrice].map((value) => (
        <text key={value} x={width - margin.right + 8} y={yFor(value) + 4} fill="rgb(148,163,184)" fontSize="11">
          {formatUsd(value)}
        </text>
      ))}
      <text x={margin.left} y={height - 12} fill="rgb(148,163,184)" fontSize="11">
        {formatShortDate(candles[0]?.time)}
      </text>
      <text x={Math.max(margin.left + 82, latestX - 42)} y={height - 12} fill="rgb(148,163,184)" fontSize="11">
        {formatShortDate(candles[candles.length - 1]?.time)}
      </text>
      {overlays.scenario && scenarioMedian.length ? (
        <text x={width - margin.right - 92} y={height - 12} fill="rgb(148,163,184)" fontSize="11">
          {formatShortDate(scenarioMedian[scenarioMedian.length - 1]?.time)}
        </text>
      ) : null}
      <text x={margin.left + innerWidth / 2 - 60} y={height - 12} fill="rgb(100,116,139)" fontSize="10">
        {visibleStartIndex + 1}-{visibleStartIndex + candles.length} / {allCandles.length}
      </text>
    </svg>
  );
}

function ScenarioMapCard({ forecast }) {
  return (
    <div className="rounded-2xl border border-slate-300/15 bg-slate-300/10 p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">7d scenario</p>
      <p className="mt-2 text-sm text-slate-300">Historical scenario from similar setups; not a prediction.</p>
      <div className="mt-4 grid grid-cols-2 gap-2 text-sm text-slate-300">
        <MiniLine label="Up probability" value={formatProbability(forecast?.up_probability)} />
        <MiniLine label="Down probability" value={formatProbability(forecast?.down_probability)} />
        <MiniLine label="Confidence" value={forecast?.confidence ?? "-"} />
        <MiniLine label="Samples" value={forecast ? `${forecast.sample_size}/${forecast.candidate_count}` : "-"} />
        <MiniLine label="Expected low" value={formatUsd(forecast?.expected_low)} />
        <MiniLine label="Expected high" value={formatUsd(forecast?.expected_high)} />
      </div>
    </div>
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

function SignalPanel({ evaluation, futures, paperSetup, futuresMetrics, probability, priceRange, shakeout, tradeFilter }) {
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
        <TradeFilterCard tradeFilter={tradeFilter} />
      </div>

      <div className="mt-4 rounded-2xl bg-black/20 p-4">
        <p className="text-sm font-medium text-slate-200">Derivatives context</p>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300 md:grid-cols-4">
          <MiniLine label="Mark" value={formatUsd(futuresMetrics?.mark_price)} />
          <MiniLine label="Index" value={formatUsd(futuresMetrics?.index_price)} />
          <MiniLine label="Funding" value={formatPct((futuresMetrics?.funding_rate ?? 0) * 100, 4)} />
          <MiniLine label="Long/short" value={formatNumber(futuresMetrics?.long_short_ratio, 2)} />
          <MiniLine label="Top acct L/S" value={formatNumber(futuresMetrics?.top_trader_long_short_ratio, 2)} />
          <MiniLine label="Top pos L/S" value={formatNumber(futuresMetrics?.top_trader_position_ratio, 2)} />
          <MiniLine label="Taker B/S" value={formatNumber(futuresMetrics?.taker_buy_sell_ratio, 2)} />
          <MiniLine label="Crowding" value={futuresMetrics?.crowding_label ? `${futuresMetrics.crowding_label} ${formatSignedNumber(futuresMetrics.crowding_score, 2)}` : "-"} />
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

function ScannerPanel({ scanner }) {
  const candidates = scanner?.candidates ?? [];
  const active = candidates.filter((candidate) => candidate.action === "GO LONG" || candidate.action === "GO SHORT");
  const rows = candidates;

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Long / Short Scanner</h2>
          <p className="text-sm text-slate-400">
            {scanner
              ? `${active.length} active setups from ${candidates.length} symbols ranked by the same closed-candle signal model.`
              : "Set BOT_SYMBOLS to scan a comma-separated futures universe."}
          </p>
        </div>
        <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-sm text-cyan-100">
          signal only
        </span>
      </div>

      {rows.length ? (
        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-white/10 text-xs uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="py-3 pr-4">Symbol</th>
                <th className="py-3 pr-4">Action</th>
                <th className="py-3 pr-4 text-right">Confidence</th>
                <th className="py-3 pr-4 text-right">Score</th>
                <th className="py-3 pr-4 text-right">24h</th>
                <th className="py-3 pr-4">Regime</th>
                <th className="py-3">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {rows.slice(0, 12).map((candidate) => (
                <tr key={candidate.symbol} className="align-top">
                  <td className="py-3 pr-4 font-semibold text-slate-100">{candidate.symbol}</td>
                  <td className="py-3 pr-4">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${scannerActionClass(candidate.action)}`}>
                      {candidate.action}
                    </span>
                  </td>
                  <td className="py-3 pr-4 text-right text-slate-200">{formatProbability(candidate.confidence)}</td>
                  <td className={`py-3 pr-4 text-right font-medium ${candidate.score > 0.15 ? "text-emerald-300" : candidate.score < -0.15 ? "text-rose-300" : "text-cyan-200"}`}>
                    {formatSignedNumber(candidate.score, 3)}
                  </td>
                  <td className={`py-3 pr-4 text-right ${candidate.change_24h >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {formatPct(candidate.change_24h)}
                  </td>
                  <td className="py-3 pr-4 text-slate-300">
                    <p>{candidate.market_regime ?? "-"}</p>
                    <p className="text-xs text-slate-500">{candidate.volatility_regime ?? ""}</p>
                  </td>
                  <td className="max-w-xl py-3 text-slate-400">{candidate.error ?? candidate.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-5 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">
          No scanner symbols are configured.
        </p>
      )}

      {scanner?.errors?.length ? (
        <p className="mt-4 rounded-2xl bg-amber-300/10 p-3 text-sm text-amber-100">
          {scanner.errors.slice(0, 2).join(" | ")}
        </p>
      ) : null}
    </section>
  );
}

function ConfidencePanel({ confidence }) {
  const factors = confidence?.factors ?? [];
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Confidence Score</h2>
          <p className="text-sm text-slate-400">
            Combined confirmation score for the current paper action.
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-sm ${confidenceBadgeClass(confidence)}`}>
          {confidence?.label ?? "WAITING"}
        </span>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-[12rem_1fr]">
        <div className="rounded-2xl bg-black/20 p-5 text-center">
          <p className={`text-4xl font-semibold ${confidenceTextClass(confidence)}`}>
            {formatNumber(confidence?.percent, 1)}%
          </p>
          <p className="mt-2 text-sm text-slate-400">{confidence?.action ?? "STAY FLAT"}</p>
        </div>
        <div className="rounded-2xl bg-black/20 p-4">
          <p className="text-sm text-slate-300">
            {confidence?.summary ?? "Waiting for signal, probability, filter, and market context."}
          </p>
          <div className="mt-4 space-y-3">
            {factors.length ? factors.map((factor) => (
              <ConfidenceBar key={factor.label} factor={factor} />
            )) : (
              <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No confidence factors yet.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function ConfidenceBar({ factor }) {
  const percent = Math.max(0, Math.min(100, Number(factor.percent ?? 0)));
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-slate-300">{factor.label}</span>
        <span className="font-medium text-slate-100">{formatNumber(percent, 1)}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${percent >= 75 ? "bg-emerald-300" : percent >= 50 ? "bg-cyan-300" : "bg-amber-300"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function SimulatorPanel({ simulator }) {
  const overall = simulator?.overall;
  const rows = (simulator?.results ?? [])
    .filter((row) => !row.error)
    .sort((a, b) => Number(b.stats?.net_expected_r ?? -99) - Number(a.stats?.net_expected_r ?? -99));
  const errors = (simulator?.results ?? []).filter((row) => row.error);

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Futures Simulator</h2>
          <p className="text-sm text-slate-400">
            {simulator?.status === "ok"
              ? `${simulator.exchange} candle replay from local history - last run ${formatTime(simulator.generated_at)}.`
              : simulator?.message ?? "Set BOT_HISTORY_DB_PATH and sync candles to enable simulator stats."}
          </p>
        </div>
        <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-sm text-cyan-100">
          offline replay
        </span>
      </div>

      {simulator?.status === "ok" ? (
        <>
          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <MiniStat label="Trades" value={overall?.total_trades ?? 0} />
            <MiniStat label="Win rate" value={formatProbability(overall?.win_rate)} />
            <MiniStat label="Net expected R" value={formatSignedNumber(overall?.net_expected_r, 2)} />
            <MiniStat label="Max drawdown" value={formatPct(overall?.max_drawdown_percent)} />
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <MiniStat label="Net PnL" value={formatUsd(overall?.total_net_pnl)} />
            <MiniStat label="Fees" value={formatUsd(overall?.total_fees)} />
            <MiniStat label="Funding" value={formatUsd(overall?.total_funding)} />
            <MiniStat label="Liq touches" value={overall?.liquidation_touch_count ?? 0} />
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <SimulatorEquityChart points={simulator.equity_curve ?? []} />
            <SimulatorSymbolBars rows={rows} />
          </div>

          <div className="mt-5 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs uppercase tracking-[0.16em] text-slate-500">
                <tr>
                  <th className="py-3 pr-4">Symbol</th>
                  <th className="py-3 pr-4 text-right">Trades</th>
                  <th className="py-3 pr-4 text-right">Win</th>
                  <th className="py-3 pr-4 text-right">Net R</th>
                  <th className="py-3 pr-4 text-right">PnL</th>
                  <th className="py-3 pr-4 text-right">Max DD</th>
                  <th className="py-3">Recent</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {rows.slice(0, 8).map((row) => (
                  <tr key={row.symbol} className="align-top">
                    <td className="py-3 pr-4 font-semibold text-slate-100">{row.symbol}</td>
                    <td className="py-3 pr-4 text-right text-slate-300">{row.stats?.total_trades ?? 0}</td>
                    <td className="py-3 pr-4 text-right text-slate-300">{formatProbability(row.stats?.win_rate)}</td>
                    <td className={`py-3 pr-4 text-right font-medium ${Number(row.stats?.net_expected_r ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {formatSignedNumber(row.stats?.net_expected_r, 2)}
                    </td>
                    <td className={`py-3 pr-4 text-right ${Number(row.stats?.total_net_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {formatUsd(row.stats?.total_net_pnl)}
                    </td>
                    <td className="py-3 pr-4 text-right text-slate-300">{formatPct(row.stats?.max_drawdown_percent)}</td>
                    <td className="py-3 text-slate-400">
                      {(row.recent_trades ?? []).length
                        ? row.recent_trades.map((trade) => `${trade.side} ${trade.outcome} ${formatSignedNumber(trade.net_r, 2)}R`).join(" | ")
                        : "No completed replay trades"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {errors.length ? (
            <p className="mt-4 rounded-2xl bg-amber-300/10 p-3 text-sm text-amber-100">
              Missing history: {errors.slice(0, 4).map((row) => row.symbol).join(", ")}
            </p>
          ) : null}
        </>
      ) : (
        <p className="mt-5 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">
          {simulator?.message ?? "Simulator data is not available yet."}
        </p>
      )}
    </section>
  );
}

function SimulatorEquityChart({ points }) {
  const chartPoints = (points ?? []).filter((point) => isFiniteNumber(point.equity));
  const width = 720;
  const height = 240;
  const margin = { top: 18, right: 26, bottom: 34, left: 64 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const equities = chartPoints.map((point) => Number(point.equity));
  const [minEquity, maxEquity] = paddedDomain(equities, 0.12);
  const xFor = (index) => margin.left + (innerWidth * index) / Math.max(1, chartPoints.length - 1);
  const yFor = (value) => margin.top + ((maxEquity - value) / Math.max(1, maxEquity - minEquity)) * innerHeight;
  const path = chartPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(2)} ${yFor(Number(point.equity)).toFixed(2)}`)
    .join(" ");
  const latest = chartPoints[chartPoints.length - 1];
  const first = chartPoints[0];
  const delta = latest && first ? Number(latest.equity) - Number(first.equity) : null;

  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-200">Equity replay</p>
          <p className="text-xs text-slate-500">Closed simulated contracts over local candle history.</p>
        </div>
        <span className={`text-sm font-semibold ${Number(delta ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
          {formatUsd(delta)}
        </span>
      </div>
      {chartPoints.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="mt-4 h-64 w-full overflow-visible">
          <line x1={margin.left} x2={width - margin.right} y1={yFor(first.equity)} y2={yFor(first.equity)} stroke="rgba(148,163,184,0.22)" strokeDasharray="5 5" />
          <path d={path} fill="none" stroke={Number(delta ?? 0) >= 0 ? "#6ee7b7" : "#fda4af"} strokeWidth="3" strokeLinecap="round" />
          {chartPoints.map((point, index) => {
            if (index === 0) return null;
            const positive = Number(point.net_pnl ?? 0) >= 0;
            return (
              <circle
                key={`${point.time ?? index}-${index}`}
                cx={xFor(index)}
                cy={yFor(Number(point.equity))}
                r="4"
                className={positive ? "fill-emerald-300" : "fill-rose-300"}
              />
            );
          })}
          <text x={margin.left} y={height - 10} className="fill-slate-500 text-[11px]">start</text>
          <text x={width - margin.right - 48} y={height - 10} className="fill-slate-500 text-[11px]">latest</text>
          <text x={8} y={yFor(maxEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(maxEquity)}</text>
          <text x={8} y={yFor(minEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(minEquity)}</text>
        </svg>
      ) : (
        <p className="mt-4 rounded-xl bg-white/5 p-4 text-sm text-slate-400">No closed replay trades yet.</p>
      )}
    </div>
  );
}

function SimulatorSymbolBars({ rows }) {
  const ranked = rows.slice(0, 8);
  const maxAbs = Math.max(
    1,
    ...ranked.map((row) => Math.abs(Number(row.stats?.total_net_pnl ?? 0)))
  );
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">Symbol performance</p>
      <div className="mt-4 space-y-3">
        {ranked.length ? ranked.map((row) => {
          const pnl = Number(row.stats?.total_net_pnl ?? 0);
          const width = Math.max(4, Math.abs(pnl) / maxAbs * 100);
          return (
            <div key={row.symbol}>
              <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                <span className="font-medium text-slate-300">{row.symbol}</span>
                <span className={pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>{formatUsd(pnl)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className={`h-full rounded-full ${pnl >= 0 ? "bg-emerald-300" : "bg-rose-300"}`}
                  style={{ width: `${width}%` }}
                />
              </div>
            </div>
          );
        }) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No symbols with replay data yet.</p>
        )}
      </div>
    </div>
  );
}

function TradeFilterCard({ tradeFilter }) {
  const status = tradeFilter?.status ?? "WAITING";
  const reasons = tradeFilter?.reasons?.length ? tradeFilter.reasons : ["Risk gates not evaluated yet."];
  const toneClass = tradeFilter?.status === "BLOCKED"
    ? "border-rose-300/25 text-rose-100"
    : tradeFilter?.status === "PASS"
      ? "border-emerald-300/25 text-emerald-100"
      : "border-cyan-300/25 text-cyan-100";

  return (
    <div className={`rounded-2xl border ${toneClass} bg-black/20 p-4`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">do-not-trade filters</p>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
          {tradeFilter?.original_action ?? "WAITING"}
        </span>
      </div>
      <p className="mt-2 text-3xl font-semibold">{status}</p>
      <div className="mt-3 space-y-2 text-sm text-slate-300">
        {reasons.map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
      </div>
    </div>
  );
}

function PaperJournalPanel({ report }) {
  const overall = report?.overall;
  const ledger = report?.ledger;
  const sideGroups = report?.groups?.side ?? {};
  const volatilityGroups = report?.groups?.volatility_regime ?? {};
  const recentTrades = report?.recent_trades ?? [];
  const sideRows = Object.entries(sideGroups).slice(0, 4);
  const volatilityRows = Object.entries(volatilityGroups).slice(0, 4);

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Paper Trade Journal</h2>
          <p className="text-sm text-slate-400">
            {report ? `${report.total_setups} recorded setups` : "Set BOT_PAPER_SETUP_JOURNAL_PATH to collect setup outcomes."}
          </p>
        </div>
        <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-sm text-cyan-100">
          paper only
        </span>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-4">
        <MiniStat label="Open" value={overall?.open_count ?? 0} />
        <MiniStat label="TP / SL" value={`${overall?.tp_count ?? 0} / ${overall?.sl_count ?? 0}`} />
        <MiniStat label="Win rate" value={formatProbability(overall?.win_rate)} />
        <MiniStat label="Expected R" value={formatSignedNumber(overall?.expected_r, 2)} />
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-5">
        <MiniStat label="Closed trades" value={ledger?.closed_trades ?? 0} />
        <MiniStat label="Net PnL" value={formatUsd(ledger?.net_pnl)} />
        <MiniStat label="Fees / slip" value={`${formatUsd(ledger?.fees)} / ${formatUsd(ledger?.slippage)}`} />
        <MiniStat label="Funding" value={formatUsd(ledger?.funding)} />
        <MiniStat label="Max drawdown" value={formatPct(ledger?.max_drawdown_percent)} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <JournalGroup title="By side" rows={sideRows} />
        <JournalGroup title="By volatility" rows={volatilityRows} />
        <RecentLedgerTrades rows={recentTrades} />
      </div>
    </section>
  );
}

function JournalGroup({ title, rows }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <div className="mt-4 space-y-3">
        {rows.length ? rows.map(([label, stats]) => (
          <div key={label} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-100">{label}</span>
              <span>{stats.total_setups} setups</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <MiniLine label="TP" value={stats.tp_count} />
              <MiniLine label="SL" value={stats.sl_count} />
              <MiniLine label="Win" value={formatProbability(stats.win_rate)} />
            </div>
          </div>
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No journal rows yet.</p>
        )}
      </div>
    </div>
  );
}

function RecentLedgerTrades({ rows }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">Recent net trades</p>
      <div className="mt-4 space-y-3">
        {rows.length ? rows.slice(-5).reverse().map((trade, index) => (
          <div key={`${trade.entry_time}-${trade.side}-${index}`} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-100">{trade.side} {trade.outcome}</span>
              <span className={Number(trade.net_pnl) >= 0 ? "text-emerald-300" : "text-rose-300"}>{formatUsd(trade.net_pnl)}</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <MiniLine label="Net R" value={formatSignedNumber(trade.net_r, 2)} />
              <MiniLine label="Costs" value={formatUsd(Number(trade.fees ?? 0) + Number(trade.slippage ?? 0))} />
              <MiniLine label="Exit" value={formatUsd(trade.exit_price)} />
            </div>
          </div>
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No closed paper trades yet.</p>
        )}
      </div>
    </div>
  );
}

function NewsPanel({ headlines, sources, events, macro }) {
  const macroEvents = macro?.events ?? [];
  const calendar = macro?.calendar;
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Market Mood</h2>
      <p className="text-sm text-slate-400">News, Fear & Greed, GDELT, and derivatives crowding used by the model.</p>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {sources.length ? sources.map((source) => (
          <div key={source.name} className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-200">{source.name}</p>
              <span className={`text-sm font-semibold ${source.score > 0.15 ? "text-emerald-300" : source.score < -0.15 ? "text-rose-300" : "text-cyan-200"}`}>
                {formatSignedNumber(source.score, 3)}
              </span>
            </div>
            <p className="mt-2 text-lg font-semibold text-slate-100">{source.label}</p>
            <p className="mt-2 text-xs text-slate-400">{source.detail}</p>
          </div>
        )) : (
          <p className="rounded-2xl bg-black/20 p-4 text-sm text-slate-400 md:col-span-3">Waiting for market mood sources.</p>
        )}
      </div>
      <div className="mt-5 grid gap-3 lg:grid-cols-2">
        <EventBuckets title="News event buckets" events={events} />
        <CalendarRiskCard calendar={calendar} macroEvents={macroEvents} />
      </div>
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
                <span>{headline.source} - {headline.category} - {headline.event_type ?? "general"}</span>
                <span>{formatTime(headline.published_at)}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-100">{headline.title}</p>
              <p className="mt-2 text-xs text-slate-400">
                Sentiment {formatNumber(headline.sentiment, 3)} - {headline.event_impact ?? "LOW"} impact - {headline.event_direction ?? "NEUTRAL"}
              </p>
            </a>
          ))
        ) : (
          <p className="rounded-2xl bg-black/20 p-4 text-sm text-slate-400">No fresh headlines are available yet.</p>
        )}
      </div>
    </section>
  );
}

function EventBuckets({ title, events }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <div className="mt-4 space-y-3">
        {events.length ? events.slice(0, 5).map((event) => (
          <div key={event.event_type} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-100">{event.event_type}</span>
              <span>{event.count} headlines</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {event.impact} - {event.direction} - avg {formatSignedNumber(event.average_sentiment, 2)}
            </p>
          </div>
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No structured event buckets yet.</p>
        )}
      </div>
    </div>
  );
}

function CalendarRiskCard({ calendar, macroEvents }) {
  const active = calendar?.active_events ?? [];
  const upcoming = calendar?.upcoming_events ?? [];
  const rows = [...active, ...upcoming].slice(0, 5);
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">Economic calendar</p>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
          {calendar?.status ?? "WAITING"}
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-400">{calendar?.reason ?? "Waiting for calendar context."}</p>
      <div className="mt-4 space-y-2">
        {rows.length ? rows.map((event) => (
          <MiniLine
            key={`${event.name}-${event.scheduled_at}`}
            label={event.name}
            value={`${formatShortDate(event.scheduled_at)} - ${event.impact}`}
          />
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No scheduled high-impact events in the lookahead window.</p>
        )}
      </div>
      {macroEvents.length ? (
        <p className="mt-3 text-xs text-slate-500">
          Macro headline buckets: {macroEvents.slice(0, 3).map((event) => event.event_type).join(", ")}
        </p>
      ) : null}
    </div>
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
  const side = action === "GO LONG"
    ? "LONG"
    : action === "GO SHORT"
      ? "SHORT"
      : !evaluation.futures && signal === "STRONG BUY"
        ? "LONG"
        : !evaluation.futures && signal === "STRONG SELL"
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

function timeframeHoursFor(timeframe) {
  const match = String(timeframe ?? "4h").trim().toLowerCase().match(/^(\d+(?:\.\d+)?)([mhd])$/);
  if (!match) return 4;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return 4;
  if (match[2] === "m") return value / 60;
  if (match[2] === "h") return value;
  if (match[2] === "d") return value * 24;
  return 4;
}

function candlesPerDayFor(timeframe) {
  return Math.max(1, Math.round(24 / timeframeHoursFor(timeframe)));
}

function trendState(candle) {
  if (!isFiniteNumber(candle?.ema20) || !isFiniteNumber(candle?.ema50)) return "flat";
  if (candle.ema20 > candle.ema50 && candle.close >= candle.ema20) return "up";
  if (candle.ema20 < candle.ema50 && candle.close <= candle.ema20) return "down";
  return "flat";
}

function trendLabel(candle) {
  const state = trendState(candle);
  if (state === "up") return "trend up";
  if (state === "down") return "trend down";
  return "range";
}

function tradeFilterTone(tradeFilter) {
  if (tradeFilter?.status === "PASS") return "positive";
  if (tradeFilter?.status === "BLOCKED") return "negative";
  if (tradeFilter?.status === "NO SETUP") return "neutral";
  return "warning";
}

function confidenceTone(confidence) {
  if (confidence?.label === "HIGH") return "positive";
  if (confidence?.label === "MEDIUM") return "neutral";
  if (confidence?.label === "LOW") return "warning";
  return "neutral";
}

function confidenceTextClass(confidence) {
  if (confidence?.label === "HIGH") return "text-emerald-300";
  if (confidence?.label === "MEDIUM") return "text-cyan-200";
  if (confidence?.label === "LOW") return "text-amber-200";
  return "text-slate-100";
}

function confidenceBadgeClass(confidence) {
  if (confidence?.label === "HIGH") return "border-emerald-300/30 bg-emerald-300/10 text-emerald-100";
  if (confidence?.label === "MEDIUM") return "border-cyan-300/30 bg-cyan-300/10 text-cyan-100";
  if (confidence?.label === "LOW") return "border-amber-300/30 bg-amber-300/10 text-amber-100";
  return "border-white/10 bg-white/5 text-slate-300";
}

function scannerActionClass(action) {
  if (action === "GO LONG") return "bg-emerald-300/15 text-emerald-200";
  if (action === "GO SHORT") return "bg-rose-300/15 text-rose-200";
  if (action === "STAY FLAT") return "bg-cyan-300/15 text-cyan-100";
  return "bg-white/10 text-slate-300";
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

function pathFromPoints(rows, xFor, yFor) {
  const points = rows
    .map((row, index) => [xFor(index), row.price])
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

function formatSignedNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
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
