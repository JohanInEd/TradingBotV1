import React from "react";
import { connectionClass, formatTime } from "../lib/format.js";

export const TABS = [
  ["overview", "Overview"],
  ["active", "Active Trader"],
  ["map", "Long / Short Map"],
  ["scanner", "Scanner"],
  ["performance", "Performance"],
  ["system", "System"]
];

export function Header({ connection, error, updatedAt, activeTab, onSelectTab, market }) {
  return (
    <header className="rounded-3xl border border-white/10 bg-white/5 p-6 shadow-glow backdrop-blur">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm uppercase tracking-[0.35em] text-cyan-200">BTC Tri-Factor</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
            Live market and news command center
          </h1>
          {market ? (
            <p className="mt-3 text-sm text-slate-300">
              {market.exchange} {market.symbol} - {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(market.price)}
              <span className={market.change_24h >= 0 ? " text-emerald-300" : " text-rose-300"}>
                {" "}{market.change_24h >= 0 ? "+" : ""}{Number(market.change_24h ?? 0).toFixed(2)}% 24h
              </span>
            </p>
          ) : (
            <p className="mt-3 max-w-2xl text-sm text-slate-300">
              Price streams through the Python service, while news sentiment and macro risk refresh on their own cadence.
            </p>
          )}
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
      <nav className="mt-5 flex flex-wrap gap-2">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => onSelectTab(key)}
            className={`rounded-xl border px-4 py-2 text-sm font-medium transition ${
              activeTab === key
                ? "border-cyan-300/60 bg-cyan-300/15 text-cyan-100"
                : "border-white/10 bg-white/5 text-slate-300 hover:border-cyan-300/40"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
    </header>
  );
}
