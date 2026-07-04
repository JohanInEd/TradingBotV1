import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import {
  candlesPerDayFor,
  confidenceTone,
  formatCompact,
  formatCompactUsd,
  formatNumber,
  formatPct,
  formatProbability,
  formatShortDate,
  formatUsd,
  isFiniteNumber,
  paddedDomain,
  pathFromPoints,
  scenarioHorizonLabel,
  seriesPath,
  shakeoutSignalContext,
  tradeFilterTone,
  trendLabel,
  trendState
} from "./lib/format.js";
import { useSnapshot } from "./lib/useSnapshot.js";
import { LoadingPanel, MetricCard, MiniLine, MiniStat } from "./components/primitives.jsx";
import { Header } from "./components/Header.jsx";
import { SignalPanel } from "./components/SignalPanel.jsx";
import { ScalpingPanel } from "./components/ScalpingPanel.jsx";
import { ActiveTraderPanel } from "./components/ActiveTraderPanel.jsx";
import { NewsPanel } from "./components/NewsPanel.jsx";
import { ConfidencePanel } from "./components/ConfidencePanel.jsx";
import { ScannerPanel } from "./components/ScannerPanel.jsx";
import { PerformancePage } from "./components/PerformancePanel.jsx";
import { SystemPage } from "./components/SystemPanel.jsx";

function App() {
  const { snapshot, connection, error } = useSnapshot();
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedTradeMode, setSelectedTradeMode] = useState("4h");

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
  const portfolioDecision = evaluation?.portfolio;
  const meta = evaluation?.meta;
  const paperJournal = snapshot?.paper_journal;
  const scalping = evaluation?.scalping;
  const scalpingJournal = snapshot?.scalping_journal;
  const activeTrader = evaluation?.active_trader;
  const portfolioState = snapshot?.portfolio_state;
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
        <Header
          connection={connection}
          error={error}
          updatedAt={snapshot?.generated_at}
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          market={market}
        />

        {!evaluation ? (
          <LoadingPanel />
        ) : (
          <>
            {activeTab === "overview" ? (
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
                    label="Market Regime"
                    value={marketContext?.volatility_regime ?? "WAITING"}
                    detail={`${marketContext?.structure_regime ?? "Closed candle context"} - ATR ${formatPct(marketContext?.atr_percent)}`}
                    tone={marketContext?.volatility_regime === "HIGH VOLATILITY" ? "negative" : marketContext?.volatility_regime === "ELEVATED VOLATILITY" ? "warning" : "neutral"}
                  />
                  <MetricCard
                    label="Signal Profile"
                    value={evaluation.signal_profile?.name ?? "baseline"}
                    detail={evaluation.signal_profile?.reason ?? "Static weights and thresholds"}
                    tone={evaluation.signal_profile?.adaptive ? "positive" : "neutral"}
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
                  <MetricCard
                    label="Portfolio"
                    value={
                      portfolioState?.kill_switch_active
                        ? "KILL SWITCH"
                        : `${portfolioState?.open_positions ?? 0} open`
                    }
                    detail={
                      portfolioDecision && !portfolioDecision.allowed
                        ? portfolioDecision.reasons?.[0]
                        : `Risk ${formatUsd(portfolioState?.open_risk_usd)} - DD ${formatPct(portfolioState?.current_drawdown_percent)}`
                    }
                    tone={
                      portfolioState?.kill_switch_active || (portfolioDecision && !portfolioDecision.allowed)
                        ? "negative"
                        : "neutral"
                    }
                  />
                  <MetricCard
                    label="Meta Gate"
                    value={meta ? (meta.tp_probability !== null && meta.tp_probability !== undefined ? `${formatProbability(meta.tp_probability)} TP` : meta.status) : "IDLE"}
                    detail={meta?.detail ?? "Scores directional setups against journal outcomes"}
                    tone={meta?.status === "BLOCKED" ? "negative" : meta?.status === "PASS" ? "positive" : "neutral"}
                  />
                  <MetricCard
                    label="5m Scalp"
                    value={scalping?.paper_setup?.action ?? scalping?.futures?.action ?? "WAITING"}
                    detail={scalping ? `Score ${formatNumber(scalping.technical?.score, 3)} - independent of the 4h signal` : "Waiting for the first closed 5m candle"}
                    tone={scalping?.futures?.side === "LONG" ? "positive" : scalping?.futures?.side === "SHORT" ? "negative" : "neutral"}
                  />
                </section>

                <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                  <ConfidencePanel confidence={confidence} />
                  <ScannerPanel scanner={scanner} compact />
                </section>

                <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
                  <SignalPanel evaluation={evaluation} futures={futures} paperSetup={paperSetup} futuresMetrics={futuresMetrics} probability={probability} priceRange={priceRange} shakeout={shakeout} tradeFilter={tradeFilter} />
                  <NewsPanel
                    headlines={allHeadlines}
                    sources={sentiment?.sources ?? []}
                    events={sentiment?.events ?? []}
                    macro={macro}
                    assetSentiment={sentiment?.asset_sentiment ?? []}
                  />
                </section>

                <section className="grid gap-4">
                  <ScalpingPanel scalping={scalping} journal={scalpingJournal} />
                </section>
              </>
            ) : null}

            {activeTab === "active" ? (
              <ActiveTraderPanel activeTrader={activeTrader} />
            ) : null}

            {activeTab === "map" ? (
              <DecisionChart
                evaluation={evaluation}
                chart={chart}
                tradeModes={tradeModes}
                selectedTimeframe={selectedTradeMode}
                onSelectTimeframe={setSelectedTradeMode}
              />
            ) : null}

            {activeTab === "scanner" ? (
              <ScannerPanel scanner={scanner} />
            ) : null}

            {activeTab === "performance" ? (
              <PerformancePage
                paperJournal={paperJournal}
                simulator={simulator}
                portfolioState={portfolioState}
              />
            ) : null}

            {activeTab === "system" ? (
              <SystemPage
                evaluation={evaluation}
                paperJournal={paperJournal}
                portfolioState={portfolioState}
              />
            ) : null}
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
    { timeframe: "30m", label: "30min Trade" },
    { timeframe: "5m", label: "5min Trade" }
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
            <LegendItem color="bg-slate-400" label={`${scenarioHorizonLabel(scenarioForecast?.horizon_hours)} scenario`} />
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
          <text x={scenarioLabelX} y={scenarioLabelY} fill="rgb(203,213,225)" fontSize="12" fontWeight="700">{scenarioHorizonLabel(scenarioForecast?.horizon_hours)} scenario</text>
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
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{scenarioHorizonLabel(forecast?.horizon_hours)} scenario</p>
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

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
