import React from "react";
import {
  driftToneClass,
  formatPct,
  formatProbability,
  formatShortDate,
  formatTime,
  formatUsd
} from "../lib/format.js";
import { MiniLine, MiniStat } from "./primitives.jsx";

export function SystemPage({ evaluation, paperJournal, portfolioState }) {
  return (
    <>
      <section className="grid gap-4 lg:grid-cols-2">
        <SignalProfileCard profile={evaluation.signal_profile} />
        <MetaModelCard meta={evaluation.meta} />
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <PortfolioStateCard portfolioState={portfolioState} decision={evaluation.portfolio} />
        <DriftCard drift={paperJournal?.drift} />
      </section>
      <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <HealthPanel evaluation={evaluation} />
        <MarketContextPanel marketContext={evaluation.market_context} />
      </section>
      <ErrorsCard errors={evaluation.errors ?? []} />
    </>
  );
}

export function SignalProfileCard({ profile }) {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Signal Profile</h2>
        <span className={`rounded-full border px-3 py-1 text-sm ${profile?.adaptive ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-100" : "border-white/10 bg-white/5 text-slate-300"}`}>
          {profile?.name ?? "baseline"}
        </span>
      </div>
      <p className="mt-3 text-sm text-slate-400">
        {profile?.reason ?? "Static configured weights and thresholds."}
      </p>
      {profile ? (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
          <MiniStat label="Buy threshold" value={Number(profile.buy_threshold).toFixed(2)} />
          <MiniStat label="Sell threshold" value={Number(profile.sell_threshold).toFixed(2)} />
          <MiniStat label="4h weight" value={formatProbability(profile.primary_weight)} />
          <MiniStat label="Daily weight" value={formatProbability(profile.daily_weight)} />
          <MiniStat label="1h weight" value={formatProbability(profile.hourly_weight)} />
          <MiniStat label="Adaptive" value={profile.adaptive ? "on" : "off"} />
        </div>
      ) : null}
    </section>
  );
}

export function MetaModelCard({ meta }) {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Meta Model Gate</h2>
        <span className={`rounded-full border px-3 py-1 text-sm ${
          meta?.status === "PASS"
            ? "border-emerald-300/30 bg-emerald-300/10 text-emerald-100"
            : meta?.status === "BLOCKED"
              ? "border-rose-300/30 bg-rose-300/10 text-rose-100"
              : "border-white/10 bg-white/5 text-slate-300"
        }`}>
          {meta?.status ?? "IDLE"}
        </span>
      </div>
      <p className="mt-3 text-sm text-slate-400">
        {meta?.detail ?? "The meta model scores directional setups against recorded journal outcomes. It reports here whenever a LONG or SHORT setup is evaluated."}
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
        <MiniStat label="TP odds" value={formatProbability(meta?.tp_probability)} />
        <MiniStat label="Threshold" value={formatProbability(meta?.threshold)} />
        <MiniStat label="Training rows" value={meta?.sample_count ?? 0} />
      </div>
    </section>
  );
}

export function PortfolioStateCard({ portfolioState, decision }) {
  const cooldowns = portfolioState?.cooldowns ?? [];
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Portfolio Limits</h2>
        <span className={`rounded-full border px-3 py-1 text-sm ${
          portfolioState?.kill_switch_active
            ? "border-rose-300/30 bg-rose-300/10 text-rose-100"
            : "border-emerald-300/30 bg-emerald-300/10 text-emerald-100"
        }`}>
          {portfolioState?.kill_switch_active ? "KILL SWITCH" : "within limits"}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
        <MiniStat label="Open positions" value={portfolioState?.open_positions ?? 0} />
        <MiniStat label="Long / Short" value={`${portfolioState?.long_positions ?? 0} / ${portfolioState?.short_positions ?? 0}`} />
        <MiniStat label="Open risk" value={formatUsd(portfolioState?.open_risk_usd)} />
        <MiniStat label="Paper equity" value={formatUsd(portfolioState?.equity)} />
        <MiniStat label="Peak equity" value={formatUsd(portfolioState?.peak_equity)} />
        <MiniStat label="Drawdown" value={formatPct(portfolioState?.current_drawdown_percent)} />
      </div>
      {portfolioState?.open_symbols?.length ? (
        <p className="mt-4 text-sm text-slate-300">
          <span className="text-slate-500">Open symbols:</span> {portfolioState.open_symbols.join(", ")}
        </p>
      ) : null}
      {cooldowns.length ? (
        <div className="mt-3 space-y-1 text-sm text-slate-300">
          {cooldowns.map(([symbol, until]) => (
            <MiniLine key={symbol} label={`${symbol} cooldown`} value={`until ${formatShortDate(until)}`} />
          ))}
        </div>
      ) : null}
      {decision && !decision.allowed ? (
        <p className="mt-4 rounded-2xl border border-rose-300/25 bg-rose-300/10 p-3 text-sm text-rose-100">
          {decision.reasons?.[0]}
        </p>
      ) : null}
    </section>
  );
}

export function DriftCard({ drift }) {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">Performance Drift</h2>
        <span className={`rounded-full border px-3 py-1 text-sm ${driftToneClass(drift?.status)}`}>
          {drift?.status ?? "NO DATA"}
        </span>
      </div>
      <p className="mt-3 text-sm text-slate-400">
        {drift?.detail ?? "Set BOT_PAPER_SETUP_JOURNAL_PATH and record enough resolved setups to compare recent results against the baseline."}
      </p>
      {drift && drift.baseline_count ? (
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
          <MiniStat label="Recent win" value={formatProbability(drift.recent_win_rate)} />
          <MiniStat label="Baseline win" value={formatProbability(drift.baseline_win_rate)} />
          <MiniStat label="Z-score" value={drift.win_rate_z !== null && drift.win_rate_z !== undefined ? Number(drift.win_rate_z).toFixed(2) : "-"} />
          <MiniStat label="Recent R" value={drift.recent_expected_r !== null && drift.recent_expected_r !== undefined ? Number(drift.recent_expected_r).toFixed(2) : "-"} />
          <MiniStat label="Baseline R" value={drift.baseline_expected_r !== null && drift.baseline_expected_r !== undefined ? Number(drift.baseline_expected_r).toFixed(2) : "-"} />
          <MiniStat label="Sample" value={`${drift.recent_count} / ${drift.baseline_count}`} />
        </div>
      ) : null}
    </section>
  );
}

export function HealthPanel({ evaluation }) {
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

export function MarketContextPanel({ marketContext }) {
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

export function ErrorsCard({ errors }) {
  if (!errors.length) return null;
  return (
    <section className="rounded-3xl border border-amber-300/20 bg-amber-300/5 p-6 shadow-glow">
      <h2 className="text-xl font-semibold text-amber-100">Recent Errors</h2>
      <div className="mt-4 space-y-2 text-sm text-amber-100/90">
        {errors.map((error) => (
          <p key={error} className="rounded-xl bg-black/20 p-3">{error}</p>
        ))}
      </div>
    </section>
  );
}
