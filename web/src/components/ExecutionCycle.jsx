import React from "react";

export const STAGE_TONE = {
  PASS: "border-emerald-300/30 bg-emerald-300/10 text-emerald-100",
  FILLED: "border-emerald-300/30 bg-emerald-300/10 text-emerald-100",
  SETTLED: "border-emerald-300/30 bg-emerald-300/10 text-emerald-100",
  BLOCKED: "border-rose-300/30 bg-rose-300/10 text-rose-100",
  PENDING: "border-amber-300/30 bg-amber-300/10 text-amber-100",
  COOLDOWN: "border-cyan-300/30 bg-cyan-300/10 text-cyan-100",
  SKIPPED: "border-white/10 bg-white/5 text-slate-400",
  IDLE: "border-white/10 bg-white/5 text-slate-400"
};

// The five-stage paper-trade lifecycle shared by the scalping signal and the
// active trader: scam detect, validate, size, fill, settle.
export function ExecutionCycleTracker({ cycle, title = "Execution cycle" }) {
  if (!cycle) return null;
  return (
    <div className="mt-4 rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <span className={`rounded-full border px-3 py-1 text-xs ${STAGE_TONE[cycle.status] ?? STAGE_TONE.IDLE}`}>
          {cycle.status}
        </span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-5">
        {(cycle.stages ?? []).map((stage) => (
          <div key={stage.name} className={`rounded-xl border p-2 ${STAGE_TONE[stage.status] ?? STAGE_TONE.IDLE}`}>
            <p className="text-[11px] uppercase tracking-[0.14em] opacity-80">{stage.name}</p>
            <p className="mt-1 text-xs font-semibold">{stage.status}</p>
          </div>
        ))}
      </div>
      <ul className="mt-3 space-y-1 text-xs text-slate-400">
        {(cycle.stages ?? []).map((stage) => (
          <li key={stage.name}>
            <span className="font-medium text-slate-300">{stage.name}:</span> {stage.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}
