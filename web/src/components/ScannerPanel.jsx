import React, { useMemo, useState } from "react";
import {
  formatCompactUsd,
  formatPct,
  formatProbability,
  formatSignedNumber,
  formatUsd,
  portfolioStatusClass,
  scannerActionClass
} from "../lib/format.js";
import { MiniStat } from "./primitives.jsx";

const SORTS = {
  rank: { label: "Rank", compare: null },
  confidence: {
    label: "Confidence",
    compare: (a, b) => Number(b.confidence ?? 0) - Number(a.confidence ?? 0)
  },
  score: {
    label: "Score",
    compare: (a, b) => Number(b.score ?? 0) - Number(a.score ?? 0)
  },
  change: {
    label: "24h",
    compare: (a, b) => Number(b.change_24h ?? -999) - Number(a.change_24h ?? -999)
  },
  symbol: {
    label: "Symbol",
    compare: (a, b) => String(a.symbol).localeCompare(String(b.symbol))
  }
};

export function ScannerPanel({ scanner, compact = false }) {
  const [sortKey, setSortKey] = useState("rank");
  const candidates = scanner?.candidates ?? [];
  const active = candidates.filter((candidate) => candidate.action === "GO LONG" || candidate.action === "GO SHORT");
  const portfolio = scanner?.portfolio;

  const rows = useMemo(() => {
    const compare = SORTS[sortKey]?.compare;
    if (!compare) return candidates;
    return [...candidates].sort(compare);
  }, [candidates, sortKey]);

  const limit = compact ? 6 : 30;

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

      {!compact && portfolio ? (
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MiniStat
            label="Open paper positions"
            value={`${portfolio.open_positions} (${portfolio.long_positions}L / ${portfolio.short_positions}S)`}
          />
          <MiniStat label="Open risk" value={formatUsd(portfolio.open_risk_usd)} />
          <MiniStat label="Paper equity" value={formatCompactUsd(portfolio.equity)} />
          <MiniStat
            label="Kill switch"
            value={portfolio.kill_switch_active ? `ACTIVE (${formatPct(portfolio.current_drawdown_percent)})` : "off"}
          />
        </div>
      ) : null}

      {!compact ? (
        <div className="mt-5 flex flex-wrap gap-2">
          {Object.entries(SORTS).map(([key, sort]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSortKey(key)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                sortKey === key
                  ? "border-cyan-300/60 bg-cyan-300/15 text-cyan-100"
                  : "border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/40"
              }`}
            >
              {sort.label}
            </button>
          ))}
        </div>
      ) : null}

      {rows.length ? (
        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-white/10 text-xs uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="py-3 pr-4">Symbol</th>
                <th className="py-3 pr-4">Action</th>
                <th className="py-3 pr-4">Portfolio</th>
                <th className="py-3 pr-4 text-right">Confidence</th>
                <th className="py-3 pr-4 text-right">Score</th>
                <th className="py-3 pr-4 text-right">Sentiment</th>
                <th className="py-3 pr-4 text-right">24h</th>
                <th className="py-3 pr-4">Regime</th>
                {compact ? null : <th className="py-3">Reason</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {rows.slice(0, limit).map((candidate) => (
                <tr key={candidate.symbol} className="align-top">
                  <td className="py-3 pr-4 font-semibold text-slate-100">{candidate.symbol}</td>
                  <td className="py-3 pr-4">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${scannerActionClass(candidate.action)}`}>
                      {candidate.action}
                    </span>
                  </td>
                  <td className="py-3 pr-4">
                    {candidate.portfolio_status ? (
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-medium ${portfolioStatusClass(candidate.portfolio_status)}`}
                        title={candidate.portfolio_status}
                      >
                        {candidate.portfolio_status.startsWith("BLOCKED") ? "BLOCKED" : candidate.portfolio_status}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-600">-</span>
                    )}
                  </td>
                  <td className="py-3 pr-4 text-right text-slate-200">{formatProbability(candidate.confidence)}</td>
                  <td className={`py-3 pr-4 text-right font-medium ${candidate.score > 0.15 ? "text-emerald-300" : candidate.score < -0.15 ? "text-rose-300" : "text-cyan-200"}`}>
                    {formatSignedNumber(candidate.score, 3)}
                  </td>
                  <td className="py-3 pr-4 text-right text-slate-300">
                    {formatSignedNumber(candidate.sentiment_score, 2)}
                    <span className="ml-1 text-xs text-slate-500">
                      {candidate.sentiment_basis === "asset" ? "asset" : "global"}
                    </span>
                  </td>
                  <td className={`py-3 pr-4 text-right ${candidate.change_24h >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {formatPct(candidate.change_24h)}
                  </td>
                  <td className="py-3 pr-4 text-slate-300">
                    <p>{candidate.market_regime ?? "-"}</p>
                    <p className="text-xs text-slate-500">{candidate.volatility_regime ?? ""}</p>
                  </td>
                  {compact ? null : (
                    <td className="max-w-xl py-3 text-slate-400">
                      {candidate.error ?? candidate.reason}
                      {candidate.portfolio_status?.startsWith("BLOCKED") ? (
                        <p className="mt-1 text-xs text-rose-200/80">{candidate.portfolio_status}</p>
                      ) : null}
                    </td>
                  )}
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
