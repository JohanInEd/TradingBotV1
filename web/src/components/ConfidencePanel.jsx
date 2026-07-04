import React from "react";
import {
  confidenceBadgeClass,
  confidenceTextClass,
  formatNumber
} from "../lib/format.js";

export function ConfidencePanel({ confidence }) {
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

export function ConfidenceBar({ factor }) {
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
