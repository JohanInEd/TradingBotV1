import React from "react";

export function MetricCard({ label, value, detail, tone }) {
  const toneClass = {
    positive: "text-emerald-300",
    negative: "text-rose-300",
    warning: "text-amber-200",
    neutral: "text-cyan-200"
  }[tone ?? "neutral"];

  return (
    <article className="rounded-3xl border border-white/10 bg-panel/80 p-5 shadow-glow">
      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">{label}</p>
      <p className={`mt-3 text-2xl font-semibold ${toneClass}`}>{value}</p>
      <p className="mt-2 text-sm text-slate-400">{detail}</p>
    </article>
  );
}

export function MiniStat({ label, value }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-100">{value}</p>
    </div>
  );
}

export function MiniLine({ label, value }) {
  return (
    <p>
      <span className="text-slate-500">{label}</span>{" "}
      <span className="font-medium text-slate-100">{value}</span>
    </p>
  );
}

export function LoadingPanel() {
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-10 text-center shadow-glow">
      <p className="text-xl font-semibold">Starting live dashboard...</p>
      <p className="mt-2 text-slate-400">The backend is connecting to market data and news feeds.</p>
    </section>
  );
}
