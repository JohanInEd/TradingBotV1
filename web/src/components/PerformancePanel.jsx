import React from "react";
import {
  driftToneClass,
  formatPct,
  formatProbability,
  formatShortDate,
  formatSignedNumber,
  formatTime,
  formatUsd,
  isFiniteNumber,
  paddedDomain
} from "../lib/format.js";
import { MiniLine, MiniStat } from "./primitives.jsx";

export function PerformancePage({ paperJournal, simulator, portfolioState }) {
  return (
    <>
      <PaperJournalPanel report={paperJournal} portfolioState={portfolioState} />
      <SimulatorPanel simulator={simulator} />
    </>
  );
}

export function PaperJournalPanel({ report, portfolioState }) {
  const overall = report?.overall;
  const ledger = report?.ledger;
  const drift = report?.drift;
  const equityCurve = report?.equity_curve ?? [];
  const sideGroups = report?.groups?.side ?? {};
  const regimeGroups = report?.groups?.market_regime ?? {};
  const volatilityGroups = report?.groups?.volatility_regime ?? {};
  const recentTrades = report?.recent_trades ?? [];
  const sideRows = Object.entries(sideGroups).slice(0, 4);
  const regimeRows = Object.entries(regimeGroups).slice(0, 5);
  const volatilityRows = Object.entries(volatilityGroups).slice(0, 4);

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Paper Portfolio</h2>
          <p className="text-sm text-slate-400">
            {report ? `${report.total_setups} recorded setups across all scanned symbols` : "Set BOT_PAPER_SETUP_JOURNAL_PATH to collect setup outcomes."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {drift ? (
            <span className={`rounded-full border px-3 py-1 text-sm ${driftToneClass(drift.status)}`} title={drift.detail}>
              drift: {drift.status}
            </span>
          ) : null}
          <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-3 py-1 text-sm text-cyan-100">
            paper only
          </span>
        </div>
      </div>

      {drift && drift.status !== "NORMAL" ? (
        <p className={`mt-4 rounded-2xl border p-3 text-sm ${driftToneClass(drift.status)}`}>
          {drift.detail}
        </p>
      ) : null}

      <div className="mt-5 grid gap-3 md:grid-cols-4">
        <MiniStat label="Open" value={overall?.open_count ?? 0} />
        <MiniStat label="TP / SL" value={`${overall?.tp_count ?? 0} / ${overall?.sl_count ?? 0}`} />
        <MiniStat label="Win rate" value={formatProbability(overall?.win_rate)} />
        <MiniStat label="Expected R" value={formatSignedNumber(overall?.expected_r, 2)} />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-5">
        <MiniStat label="Closed trades" value={ledger?.closed_trades ?? 0} />
        <MiniStat label="Net PnL" value={formatUsd(ledger?.net_pnl)} />
        <MiniStat label="Fees / slip" value={`${formatUsd(ledger?.fees)} / ${formatUsd(ledger?.slippage)}`} />
        <MiniStat label="Return" value={formatPct(ledger?.return_percent)} />
        <MiniStat label="Max drawdown" value={formatPct(ledger?.max_drawdown_percent)} />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <PortfolioEquityChart points={equityCurve} portfolioState={portfolioState} />
        <RDistribution points={equityCurve} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <JournalGroup title="By side" rows={sideRows} />
        <JournalGroup title="By market regime" rows={regimeRows} />
        <JournalGroup title="By volatility" rows={volatilityRows} />
      </div>

      <div className="mt-5">
        <RecentLedgerTrades rows={recentTrades} />
      </div>
    </section>
  );
}

export function PortfolioEquityChart({ points, portfolioState }) {
  const chartPoints = (points ?? []).filter((point) => isFiniteNumber(point.equity));
  const width = 720;
  const height = 250;
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
  const maxConcurrent = Math.max(1, ...chartPoints.map((point) => Number(point.open_positions ?? 0)));

  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-200">Portfolio equity</p>
          <p className="text-xs text-slate-500">
            One shared paper equity across every symbol; bars show concurrent open positions at each exit.
          </p>
        </div>
        <span className={`text-sm font-semibold ${Number(delta ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
          {formatUsd(delta)}
        </span>
      </div>
      {chartPoints.length > 1 ? (
        <svg viewBox={`0 0 ${width} ${height}`} className="mt-4 h-64 w-full overflow-visible">
          <line x1={margin.left} x2={width - margin.right} y1={yFor(first.equity)} y2={yFor(first.equity)} stroke="rgba(148,163,184,0.22)" strokeDasharray="5 5" />
          {chartPoints.map((point, index) => {
            const concurrent = Number(point.open_positions ?? 0);
            if (!concurrent || index === 0) return null;
            const barHeight = (concurrent / maxConcurrent) * 26;
            return (
              <rect
                key={`bar-${point.time ?? index}-${index}`}
                x={xFor(index) - 2.5}
                y={height - margin.bottom - barHeight}
                width={5}
                height={barHeight}
                fill="rgba(103,232,249,0.35)"
              />
            );
          })}
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
              >
                <title>
                  {`${point.symbol ?? ""} ${point.side ?? ""} ${point.outcome ?? ""} ${formatUsd(point.net_pnl)} @ ${formatShortDate(point.time)}`}
                </title>
              </circle>
            );
          })}
          <text x={8} y={yFor(maxEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(maxEquity)}</text>
          <text x={8} y={yFor(minEquity) + 4} className="fill-slate-500 text-[11px]">{formatUsd(minEquity)}</text>
          <text x={margin.left} y={height - 10} className="fill-slate-500 text-[11px]">start</text>
          <text x={width - margin.right - 48} y={height - 10} className="fill-slate-500 text-[11px]">latest</text>
        </svg>
      ) : (
        <p className="mt-4 rounded-xl bg-white/5 p-4 text-sm text-slate-400">No closed paper trades yet.</p>
      )}
      {portfolioState ? (
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-300 md:grid-cols-4">
          <MiniLine label="Open now" value={portfolioState.open_positions} />
          <MiniLine label="Open risk" value={formatUsd(portfolioState.open_risk_usd)} />
          <MiniLine label="Drawdown" value={formatPct(portfolioState.current_drawdown_percent)} />
          <MiniLine label="Kill switch" value={portfolioState.kill_switch_active ? "ACTIVE" : "off"} />
        </div>
      ) : null}
    </div>
  );
}

export function RDistribution({ points }) {
  const values = (points ?? [])
    .map((point) => Number(point.net_r))
    .filter((value) => Number.isFinite(value));
  const buckets = [
    ["<= -1R", (value) => value <= -1],
    ["-1R to 0", (value) => value > -1 && value < 0],
    ["0 to +1R", (value) => value >= 0 && value < 1],
    ["+1R to +2R", (value) => value >= 1 && value < 2],
    [">= +2R", (value) => value >= 2]
  ].map(([label, test]) => [label, values.filter(test).length]);
  const maxCount = Math.max(1, ...buckets.map(([, count]) => count));

  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">Net R distribution</p>
      <p className="text-xs text-slate-500">{values.length} closed paper trades</p>
      <div className="mt-4 space-y-3">
        {buckets.map(([label, count]) => (
          <div key={label}>
            <div className="mb-1 flex items-center justify-between gap-3 text-xs">
              <span className="font-medium text-slate-300">{label}</span>
              <span className="text-slate-400">{count}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/10">
              <div
                className={`h-full rounded-full ${label.startsWith("<=") || label.startsWith("-1") ? "bg-rose-300" : "bg-emerald-300"}`}
                style={{ width: `${Math.max(count ? 6 : 0, (count / maxCount) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function JournalGroup({ title, rows }) {
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

export function RecentLedgerTrades({ rows }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">Recent net trades</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rows.length ? rows.slice(-6).reverse().map((trade, index) => (
          <div key={`${trade.entry_time}-${trade.side}-${index}`} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-100">
                {trade.symbol && trade.symbol !== "?" ? `${trade.symbol} ` : ""}{trade.side} {trade.outcome}
              </span>
              <span className={Number(trade.net_pnl) >= 0 ? "text-emerald-300" : "text-rose-300"}>{formatUsd(trade.net_pnl)}</span>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <MiniLine label="Net R" value={formatSignedNumber(trade.net_r, 2)} />
              <MiniLine label="Costs" value={formatUsd(Number(trade.fees ?? 0) + Number(trade.slippage ?? 0))} />
              <MiniLine label="Exit" value={formatUsd(trade.exit_price)} />
            </div>
          </div>
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400 md:col-span-2 xl:col-span-3">No closed paper trades yet.</p>
        )}
      </div>
    </div>
  );
}

export function SimulatorPanel({ simulator }) {
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

export function SimulatorEquityChart({ points }) {
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

export function SimulatorSymbolBars({ rows }) {
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
