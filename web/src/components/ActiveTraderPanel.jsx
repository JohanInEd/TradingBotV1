import React from "react";
import {
  formatNumber,
  formatPct,
  formatProbability,
  formatShortDate,
  formatSignedNumber,
  formatUsd,
  isFiniteNumber,
  paddedDomain
} from "../lib/format.js";
import { MiniLine, MiniStat } from "./primitives.jsx";
import { ExecutionCycleTracker } from "./ExecutionCycle.jsx";

export function ActiveTraderPanel({ activeTrader }) {
  const account = activeTrader?.account;
  const position = account?.open_position;
  const growth = activeTrader?.growth_curve ?? [];
  const fills = activeTrader?.recent_fills ?? [];
  const cycleHistory = activeTrader?.cycle_history ?? [];
  const earlyTpCount = fills.filter((fill) => fill.exit_reason === "EARLY_TP" || fill.exit_reason === "PROGRESS_TP").length;
  const lastExit = fills.length ? fills[fills.length - 1] : null;
  const intervalLabel = formatInterval(activeTrader?.interval_seconds ?? 1);
  const gain = Number(account?.return_percent ?? 0) >= 0;
  const demoMode = activeTrader?.execution_mode === "binance_demo";

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-4 shadow-glow sm:p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Active Trader</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">
            BTC paper execution with a fresh scam-detect, validate, size, fill, and settle cycle every {intervalLabel}.
          </p>
        </div>
        <span className={`w-fit rounded-full border px-3 py-1 text-sm ${demoMode ? "border-amber-300/30 bg-amber-300/10 text-amber-100" : "border-emerald-300/30 bg-emerald-300/10 text-emerald-100"}`}>
          {activeTrader ? `${demoMode ? "Binance Demo" : "Paper"} - ${activeTrader.last_action ?? "IDLE"}` : "waiting"}
        </span>
      </div>

      {!activeTrader ? (
        <p className="mt-6 rounded-2xl bg-black/20 p-4 text-sm text-slate-400">
          Set BOT_ACTIVE_TRADER_ENABLED=true and wait for the first closed 5-minute candle.
        </p>
      ) : (
        <>
          <AccountSnapshot
            account={account}
            earlyTpCount={earlyTpCount}
            lastExit={lastExit}
          />

          <OpenPositionCard position={position} account={account} activeTrader={activeTrader} />

          {activeTrader.scam_alert ? (
            <div className="mt-4 rounded-2xl border border-rose-300/30 bg-rose-300/10 p-4 text-sm text-rose-100">
              <p className="font-semibold">Scam detect alert</p>
              <p className="mt-1 text-rose-100/80">{activeTrader.scam_alert}</p>
            </div>
          ) : null}

          {activeTrader.cooldown_detail ? (
            <div className="mt-4 rounded-2xl border border-cyan-300/30 bg-cyan-300/10 p-4 text-sm text-cyan-100">
              <p className="font-semibold">Cooldown active</p>
              <p className="mt-1 text-cyan-100/80">{activeTrader.cooldown_detail}</p>
            </div>
          ) : null}

          <ExecutionCycleTracker cycle={activeTrader.execution_cycle} title="This cycle" />

          <CycleLifecycleGraph rows={cycleHistory} />

          {activeTrader.last_detail ? (
            <p className="mt-3 text-xs text-cyan-100/80">{activeTrader.last_detail}</p>
          ) : null}

          <RecentFills rows={fills} />

          <PnlGrowthChart points={growth} startingEquity={account?.starting_equity ?? 100} gain={gain} />

          <p className="mt-4 text-xs text-slate-500">{activeTrader.disclaimer}</p>
        </>
      )}
    </section>
  );
}

function AccountSnapshot({ account, earlyTpCount, lastExit }) {
  return (
    <div className="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <MiniStat label="Starting" value={formatUsd(account?.starting_equity)} />
      <MiniStat label="Equity" value={formatUsd(account?.equity)} />
      <MiniStat label="Live return" value={formatPct(account?.open_total_return_percent)} />
      <MiniStat label="Win rate" value={formatProbability(account?.win_rate)} />
      <MiniStat label="Closed trades" value={account?.closed_trades ?? 0} />
      <MiniStat label="Last exit" value={lastExit ? formatExitReason(lastExit.exit_reason) : earlyTpCount ? `${earlyTpCount} early TP` : "-"} />
    </div>
  );
}

function CycleLifecycleGraph({ rows }) {
  const points = (rows ?? []).slice(-42);
  if (!points.length) {
    return (
      <div className="mt-5 rounded-2xl bg-black/20 p-4">
        <p className="text-sm font-medium text-slate-100">Cycle lifecycle</p>
        <p className="mt-3 rounded-xl bg-white/5 p-3 text-sm text-slate-400">
          Waiting for active-trader cycle history.
        </p>
      </div>
    );
  }

  const stages = [
    ["scam_status", "Scam"],
    ["validate_status", "Validate"],
    ["size_status", "Size"],
    ["fill_status", "Fill"],
    ["settle_status", "Settle"]
  ];
  const width = 720;
  const height = 210;
  const margin = { top: 18, right: 18, bottom: 34, left: 76 };
  const innerWidth = width - margin.left - margin.right;
  const rowGap = 30;
  const xFor = (index) => margin.left + (innerWidth * index) / Math.max(1, points.length - 1);
  const yFor = (index) => margin.top + index * rowGap;
  const scoreBase = margin.top + stages.length * rowGap + 18;
  const scorePath = points
    .map((point, index) => {
      const score = Math.max(-1, Math.min(1, Number(point.technical_score ?? 0)));
      const y = scoreBase - score * 18;
      return `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const latest = points[points.length - 1];

  return (
    <div className="mt-5 rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-100">Cycle lifecycle</p>
          <p className="mt-1 text-xs text-slate-500">Recent scam-detect, validate, size, fill, and settle outcomes.</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs ${statusBadgeClass(latest.status)}`}>
          {latest.status}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-4 h-auto w-full overflow-visible" role="img" aria-label="Active trader cycle lifecycle">
        {stages.map(([, label], index) => (
          <g key={label}>
            <text x="8" y={yFor(index) + 4} className="fill-slate-500 text-[11px]">{label}</text>
            <line x1={margin.left} x2={width - margin.right} y1={yFor(index)} y2={yFor(index)} stroke="rgba(148,163,184,0.14)" />
          </g>
        ))}
        {points.map((point, pointIndex) => (
          <g key={`${point.recorded_at ?? pointIndex}-${pointIndex}`}>
            {stages.map(([key], stageIndex) => (
              <circle
                key={key}
                cx={xFor(pointIndex)}
                cy={yFor(stageIndex)}
                r={pointIndex === points.length - 1 ? 5 : 4}
                className={statusDotClass(point[key])}
              >
                <title>{`${formatShortDate(point.recorded_at)} ${point.side} ${key.replace("_status", "")}: ${point[key]} - ${point.detail}`}</title>
              </circle>
            ))}
          </g>
        ))}
        <line x1={margin.left} x2={width - margin.right} y1={scoreBase} y2={scoreBase} stroke="rgba(148,163,184,0.18)" strokeDasharray="4 5" />
        <path d={scorePath} fill="none" stroke="rgba(125,211,252,0.86)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <text x="8" y={scoreBase + 4} className="fill-slate-500 text-[11px]">Bias</text>
        <text x={margin.left} y={height - 8} className="fill-slate-500 text-[11px]">{formatShortDate(points[0]?.recorded_at)}</text>
        <text x={width - margin.right - 80} y={height - 8} className="fill-slate-500 text-[11px]">{formatShortDate(latest?.recorded_at)}</text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
        <LegendSwatch className="bg-emerald-300" label="pass/fill" />
        <LegendSwatch className="bg-rose-300" label="blocked" />
        <LegendSwatch className="bg-cyan-300" label="cooldown" />
        <LegendSwatch className="bg-amber-300" label="pending" />
        <LegendSwatch className="bg-slate-500" label="skipped" />
      </div>
    </div>
  );
}

function LegendSwatch({ className, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${className}`} />
      {label}
    </span>
  );
}

function statusDotClass(status) {
  if (status === "PASS" || status === "FILLED" || status === "SETTLED") return "fill-emerald-300";
  if (status === "BLOCKED") return "fill-rose-300";
  if (status === "COOLDOWN") return "fill-cyan-300";
  if (status === "PENDING") return "fill-amber-300";
  return "fill-slate-500";
}

function statusBadgeClass(status) {
  if (status === "FILLED" || status === "SETTLED") return "border-emerald-300/30 bg-emerald-300/10 text-emerald-100";
  if (status === "BLOCKED") return "border-rose-300/30 bg-rose-300/10 text-rose-100";
  if (status === "COOLDOWN") return "border-cyan-300/30 bg-cyan-300/10 text-cyan-100";
  if (status === "PENDING") return "border-amber-300/30 bg-amber-300/10 text-amber-100";
  return "border-white/10 bg-white/5 text-slate-400";
}

function OpenPositionCard({ position, account, activeTrader }) {
  const demoMode = activeTrader?.execution_mode === "binance_demo";
  const orderLabel = demoMode ? "demo orders enabled" : "no order placed";
  if (!position) {
    return (
      <div className="mt-4 rounded-2xl border border-cyan-300/20 bg-black/20 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-slate-100">Open position</p>
          <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">{orderLabel}</span>
        </div>
        <p className="mt-3 text-3xl font-semibold text-cyan-200">FLAT</p>
        <p className="mt-2 text-sm text-slate-400">{activeTrader?.execution_status ?? "No position is open."}</p>
      </div>
    );
  }

  const long = position.side === "LONG";
  const unrealized = Number(account?.unrealized_pnl ?? 0);
  const roi = Number(account?.unrealized_roi_percent ?? 0);
  const progress = Math.max(-100, Math.min(100, Number(account?.open_progress_percent ?? 0)));
  const barWidth = `${Math.min(100, Math.abs(progress)).toFixed(0)}%`;
  const unrealizedPositive = unrealized >= 0;
  const liveEquity = Number(account?.equity ?? 0) + unrealized;
  const protectedStop = position.protected_stop_loss ?? position.stop_loss;
  const stopLabel = protectedStop !== position.stop_loss ? "Protected stop" : "Stop loss";
  const sideClass = long ? "border-emerald-300/30 text-emerald-200" : "border-rose-300/30 text-rose-200";
  const barClass = progress >= 0 ? "bg-emerald-300" : "bg-rose-300";

  return (
    <div className={`mt-4 rounded-2xl border bg-black/20 p-4 sm:p-5 ${sideClass}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-100">Open position</p>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-200">
          {position.open_order_id ? `demo order ${position.open_order_id}` : orderLabel}
        </span>
      </div>

      <p className="mt-3 text-3xl font-semibold">{position.side}</p>

      <div className="mt-4 rounded-2xl bg-white/5 p-3 sm:p-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">Live open PnL</p>
            <p className={`mt-1 text-2xl font-semibold ${unrealizedPositive ? "text-emerald-300" : "text-rose-300"}`}>
              {formatUsd(unrealized)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs uppercase tracking-[0.14em] text-slate-500">ROI on margin</p>
            <p className={`mt-1 text-xl font-semibold ${roi >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
              {formatPct(roi)}
            </p>
          </div>
        </div>

        <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10" aria-label="Progress to settlement target">
          <div className={`h-full rounded-full ${barClass}`} style={{ width: barWidth }} />
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-500">
          <span>SL {formatPct(account?.open_distance_to_stop_percent)}</span>
          <span className="text-center">{formatSignedNumber(progress, 0)}% to TP</span>
          <span className="text-right">TP {formatPct(account?.open_distance_to_target_percent)}</span>
        </div>
      </div>

      <div className="mt-4 grid gap-x-8 gap-y-3 text-sm text-slate-300 md:grid-cols-2">
        <MiniLine label="Entry" value={formatUsd(position.entry_price)} />
        <MiniLine label="Mark" value={formatUsd(account?.mark_price)} />
        <MiniLine label="Live equity" value={formatUsd(liveEquity)} />
        <MiniLine label="Margin" value={formatUsd(account?.open_margin)} />
        <MiniLine label={stopLabel} value={formatUsd(protectedStop)} />
        <MiniLine label="Take profit" value={formatUsd(position.take_profit)} />
        <MiniLine label="Reward/risk" value={`${formatNumber(position.reward_to_risk, 2)}R`} />
        <MiniLine label="Max loss" value={formatUsd(position.max_loss)} />
        <MiniLine label="Quantity" value={`${formatNumber(position.quantity_btc, 6)} BTC`} />
        <MiniLine label="Notional" value={formatUsd(position.notional)} />
        {demoMode ? <MiniLine label="Order status" value={position.open_order_status ?? activeTrader?.execution_status ?? "-"} /> : null}
      </div>
    </div>
  );
}

function RecentFills({ rows }) {
  return (
    <div className="mt-5 rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-100">Recent settled fills</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {rows.length ? rows.slice(-6).reverse().map((fill, index) => {
          const positive = Number(fill.net_pnl ?? 0) >= 0;
          return (
            <div key={`${fill.closed_at ?? index}-${index}`} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-100">{fill.side} {formatExitReason(fill.exit_reason ?? fill.outcome)}</span>
                <span className={positive ? "text-emerald-300" : "text-rose-300"}>{formatUsd(fill.net_pnl)}</span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <MiniLine label="Net R" value={formatSignedNumber(fill.net_r, 2)} />
                <MiniLine label="ROI" value={formatPct(fill.roi_percent)} />
                <MiniLine label="Exit" value={formatUsd(fill.exit_price)} />
              </div>
              {fill.execution_mode === "binance_demo" ? (
                <p className="mt-2 text-xs text-slate-500">Close order {fill.close_order_id ?? "-"} {fill.close_order_status ?? ""}</p>
              ) : null}
            </div>
          );
        }) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400 md:col-span-2">
            No settled paper trades yet.
          </p>
        )}
      </div>
    </div>
  );
}

export function PnlGrowthChart({ points, startingEquity, gain }) {
  const chartPoints = (points ?? []).filter((point) => isFiniteNumber(point.equity));
  const width = 760;
  const height = 180;
  const margin = { top: 18, right: 26, bottom: 28, left: 66 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const base = Number(startingEquity ?? 100);
  const equities = chartPoints.map((point) => Number(point.equity));
  const [minEquity, maxEquity] = paddedDomain([...equities, base], 0.12);
  const xFor = (index) => margin.left + (innerWidth * index) / Math.max(1, chartPoints.length - 1);
  const yFor = (value) => margin.top + ((maxEquity - value) / Math.max(1e-9, maxEquity - minEquity)) * innerHeight;
  const line = chartPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(2)} ${yFor(Number(point.equity)).toFixed(2)}`)
    .join(" ");
  const latest = chartPoints[chartPoints.length - 1];
  const delta = latest ? Number(latest.equity) - base : 0;
  const stroke = gain ? "#6ee7b7" : "#fda4af";

  return (
    <div className="mt-5 rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-100">PnL growth</p>
        <span className={`text-sm font-semibold ${delta >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
          {formatUsd(delta)}
        </span>
      </div>
      {chartPoints.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="mt-3 h-44 w-full overflow-visible" role="img" aria-label="Active trader PnL growth">
          <line x1={margin.left} x2={width - margin.right} y1={yFor(base)} y2={yFor(base)} stroke="rgba(148,163,184,0.28)" strokeDasharray="5 5" />
          <path d={line} fill="none" stroke={stroke} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
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
              >
                <title>
                  {`${point.side ?? ""} ${formatExitReason(point.exit_reason ?? point.outcome)} ${formatUsd(point.net_pnl)} (${formatSignedNumber(point.net_r, 2)}R) -> ${formatUsd(point.equity)} @ ${formatShortDate(point.time)}`}
                </title>
              </circle>
            );
          })}
          <text x={8} y={yFor(maxEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(maxEquity)}</text>
          <text x={8} y={yFor(minEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(minEquity)}</text>
        </svg>
      ) : (
        <p className="mt-3 rounded-xl bg-white/5 p-3 text-sm text-slate-400">
          No settled trades yet. The curve grows as each paper position settles.
        </p>
      )}
    </div>
  );
}

function formatExitReason(reason) {
  const normalized = String(reason ?? "").toUpperCase();
  if (normalized === "EARLY_TP") return "early TP";
  if (normalized === "PROGRESS_TP") return "progress TP";
  if (normalized === "TARGET_HIT" || normalized === "TP") return "target hit";
  if (normalized === "PROTECTED_STOP") return "protected stop";
  if (normalized === "STOP_LOSS" || normalized === "SL") return "stop loss";
  if (normalized === "EXPIRED") return "expired";
  return normalized ? normalized.toLowerCase().replaceAll("_", " ") : "-";
}

function formatInterval(seconds) {
  const value = Number(seconds ?? 1);
  if (!Number.isFinite(value) || value <= 1) return "1s";
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = value / 60;
  return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)}m`;
}
