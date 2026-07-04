import React from "react";
import {
  formatAgeSeconds,
  formatCompactUsd,
  formatNumber,
  formatPct,
  formatProbability,
  formatRatio,
  formatShortDate,
  formatSignedNumber,
  formatUsd,
  shakeoutSignalContext
} from "../lib/format.js";
import { MiniLine, MiniStat } from "./primitives.jsx";

export function SignalPanel({ evaluation, futures, paperSetup, futuresMetrics, probability, priceRange, shakeout, tradeFilter }) {
  const technical = evaluation.live_technical ?? evaluation.technical;
  const shakeoutContext = shakeoutSignalContext(shakeout, evaluation.signal);
  const portfolio = evaluation.portfolio;
  const meta = evaluation.meta;
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

      {portfolio || meta ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {portfolio ? (
            <div className={`rounded-2xl border bg-black/20 p-4 ${portfolio.allowed ? "border-emerald-300/25" : "border-rose-300/25"}`}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-200">portfolio limits</p>
                <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">{portfolio.status}</span>
              </div>
              <div className="mt-3 space-y-1 text-sm text-slate-300">
                {(portfolio.reasons ?? []).map((reason) => (
                  <p key={reason}>{reason}</p>
                ))}
              </div>
            </div>
          ) : null}
          {meta ? (
            <div className={`rounded-2xl border bg-black/20 p-4 ${meta.status === "BLOCKED" ? "border-rose-300/25" : "border-cyan-300/25"}`}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-200">meta model gate</p>
                <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
                  {meta.tp_probability !== null && meta.tp_probability !== undefined
                    ? `${formatProbability(meta.tp_probability)} TP odds`
                    : meta.status}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-300">{meta.detail}</p>
            </div>
          ) : null}
        </div>
      ) : null}

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

export function PaperSetupCard({ paperSetup, futures }) {
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

export function TradeFilterCard({ tradeFilter }) {
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
