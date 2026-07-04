import React from "react";
import {
  formatNumber,
  formatShortDate,
  formatUsd
} from "../lib/format.js";
import { MiniLine, MiniStat } from "./primitives.jsx";
import { ExecutionCycleTracker } from "./ExecutionCycle.jsx";

export function ScalpingPanel({ scalping, journal }) {
  const technical = scalping?.technical;
  const setup = scalping?.paper_setup;
  const futures = scalping?.futures;
  const overall = journal?.overall;

  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-semibold">5-Minute Scalp Signal</h2>
          <p className="text-sm text-slate-400">
            Independent closed-5m-candle technical signal with a tight paper stop/target. Not related to the 4h main signal.
          </p>
        </div>
        <span className="rounded-full border border-purple-300/30 bg-purple-300/10 px-3 py-1 text-sm text-purple-100">
          {scalping ? "closed 5m candle" : "waiting"}
        </span>
      </div>

      {!scalping ? (
        <p className="mt-6 text-sm text-slate-400">
          Set BOT_SCALPING_ENABLED=true (default) and wait for the first closed 5-minute candle.
        </p>
      ) : (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <MiniStat label="5m technical" value={formatNumber(technical?.score, 3)} />
            <MiniStat label="RSI 14" value={formatNumber(technical?.rsi14, 2)} />
            <MiniStat label="MACD hist" value={formatNumber(technical?.macd_histogram, 3)} />
          </div>

          <div className="mt-4">
            {setup ? (
              <div
                className={`rounded-2xl border bg-black/20 p-4 ${
                  setup.side === "LONG" ? "border-emerald-300/25" : "border-rose-300/25"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-slate-200">scalp paper setup</p>
                  <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">no order placed</span>
                </div>
                <p className={`mt-2 text-3xl font-semibold ${setup.side === "LONG" ? "text-emerald-200" : "text-rose-200"}`}>
                  {setup.action}
                </p>
                <p className="mt-2 text-sm text-slate-400">
                  Closed candle {formatShortDate(setup.candle_time)} - {setup.disclaimer}
                </p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-300">
                  <MiniLine label="Entry" value={formatUsd(setup.entry_price)} />
                  <MiniLine label="Stop loss" value={formatUsd(setup.stop_loss)} />
                  <MiniLine label="Take profit" value={formatUsd(setup.take_profit)} />
                  <MiniLine label="Reward/risk" value={`${formatNumber(setup.reward_to_risk, 2)}R`} />
                  <MiniLine label="Max loss" value={formatUsd(setup.max_loss)} />
                  <p className="col-span-2">
                    <span className="text-slate-500">Position est.</span>{" "}
                    <span className="font-medium text-slate-100">{setup.position_estimate}</span>
                  </p>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl bg-black/20 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-slate-200">scalp paper setup</p>
                  <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">no order placed</span>
                </div>
                <p className="mt-2 text-3xl font-semibold text-purple-200">{futures?.action ?? "STAY FLAT"}</p>
                <p className="mt-2 text-sm text-slate-400">{futures?.reason ?? "No closed 5m scalp setup."}</p>
              </div>
            )}
          </div>

          <ExecutionCycleTracker cycle={scalping?.execution_cycle} />

          {journal ? (
            <div className="mt-4 rounded-2xl border border-purple-300/20 bg-purple-300/10 p-4">
              <p className="text-sm font-medium text-purple-100">Scalp journal (BOT_SCALPING_JOURNAL_PATH)</p>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-slate-300 md:grid-cols-4">
                <MiniLine label="Total" value={overall?.total_setups ?? 0} />
                <MiniLine label="Open" value={overall?.open_count ?? 0} />
                <MiniLine label="Win rate" value={overall?.win_rate !== null && overall?.win_rate !== undefined ? `${(overall.win_rate * 100).toFixed(0)}%` : "-"} />
                <MiniLine label="Expected R" value={formatNumber(overall?.expected_r, 2)} />
              </div>
              {journal.ledger ? (
                <div className="mt-3 grid grid-cols-2 gap-3 text-sm text-slate-300 md:grid-cols-4">
                  <MiniLine label="Net PnL" value={formatUsd(journal.ledger.net_pnl)} />
                  <MiniLine label="Return" value={`${formatNumber(journal.ledger.return_percent, 2)}%`} />
                  <MiniLine label="Max DD" value={`${formatNumber(journal.ledger.max_drawdown_percent, 2)}%`} />
                  <MiniLine label="Closed trades" value={journal.ledger.closed_trades ?? 0} />
                </div>
              ) : null}
            </div>
          ) : (
            <p className="mt-4 text-xs text-slate-500">
              Set BOT_SCALPING_JOURNAL_PATH to track scalp setup outcomes over time.
            </p>
          )}
        </>
      )}
    </section>
  );
}
