import React from "react";
import {
  formatNumber,
  formatShortDate,
  formatSignedNumber,
  formatTime
} from "../lib/format.js";
import { MiniLine } from "./primitives.jsx";

export function NewsPanel({ headlines, sources, events, macro, assetSentiment = [] }) {
  const macroEvents = macro?.events ?? [];
  const calendar = macro?.calendar;
  return (
    <section className="rounded-3xl border border-white/10 bg-panel/80 p-6 shadow-glow">
      <h2 className="text-xl font-semibold">Market Mood</h2>
      <p className="text-sm text-slate-400">News, Fear & Greed, GDELT, and derivatives crowding used by the model.</p>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {sources.length ? sources.map((source) => (
          <div key={source.name} className="rounded-2xl border border-white/10 bg-black/20 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-200">{source.name}</p>
              <span className={`text-sm font-semibold ${source.score > 0.15 ? "text-emerald-300" : source.score < -0.15 ? "text-rose-300" : "text-cyan-200"}`}>
                {formatSignedNumber(source.score, 3)}
              </span>
            </div>
            <p className="mt-2 text-lg font-semibold text-slate-100">{source.label}</p>
            <p className="mt-2 text-xs text-slate-400">{source.detail}</p>
          </div>
        )) : (
          <p className="rounded-2xl bg-black/20 p-4 text-sm text-slate-400 md:col-span-3">Waiting for market mood sources.</p>
        )}
      </div>

      {assetSentiment.length ? (
        <div className="mt-5 rounded-2xl bg-black/20 p-4">
          <p className="text-sm font-medium text-slate-200">Per-asset headline sentiment</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {assetSentiment.map((asset) => (
              <span
                key={asset.asset}
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  asset.score > 0.15
                    ? "bg-emerald-300/15 text-emerald-200"
                    : asset.score < -0.15
                      ? "bg-rose-300/15 text-rose-200"
                      : "bg-cyan-300/10 text-cyan-100"
                }`}
              >
                {asset.asset} {formatSignedNumber(asset.score, 2)} ({asset.headline_count})
              </span>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            The scanner scores each coin with its own headlines when at least two are available.
          </p>
        </div>
      ) : null}

      <div className="mt-5 grid gap-3 lg:grid-cols-2">
        <EventBuckets title="News event buckets" events={events} />
        <CalendarRiskCard calendar={calendar} macroEvents={macroEvents} />
      </div>
      <div className="mt-5 space-y-3">
        {headlines.length ? (
          headlines.map((headline) => (
            <a
              key={`${headline.source}-${headline.title}`}
              href={headline.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="block rounded-2xl border border-white/10 bg-black/20 p-4 transition hover:border-cyan-300/50 hover:bg-cyan-300/10"
            >
              <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                <span>
                  {headline.source} - {headline.category} - {headline.event_type ?? "general"}
                  {headline.assets?.length ? ` - ${headline.assets.join("/")}` : ""}
                </span>
                <span>{formatTime(headline.published_at)}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-100">{headline.title}</p>
              <p className="mt-2 text-xs text-slate-400">
                Sentiment {formatNumber(headline.sentiment, 3)} - {headline.event_impact ?? "LOW"} impact - {headline.event_direction ?? "NEUTRAL"}
              </p>
            </a>
          ))
        ) : (
          <p className="rounded-2xl bg-black/20 p-4 text-sm text-slate-400">No fresh headlines are available yet.</p>
        )}
      </div>
    </section>
  );
}

export function EventBuckets({ title, events }) {
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <div className="mt-4 space-y-3">
        {events.length ? events.slice(0, 5).map((event) => (
          <div key={event.event_type} className="rounded-xl bg-white/5 p-3 text-sm text-slate-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-slate-100">{event.event_type}</span>
              <span>{event.count} headlines</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {event.impact} - {event.direction} - avg {formatSignedNumber(event.average_sentiment, 2)}
            </p>
          </div>
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No structured event buckets yet.</p>
        )}
      </div>
    </div>
  );
}

export function CalendarRiskCard({ calendar, macroEvents }) {
  const active = calendar?.active_events ?? [];
  const upcoming = calendar?.upcoming_events ?? [];
  const rows = [...active, ...upcoming].slice(0, 5);
  return (
    <div className="rounded-2xl bg-black/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-200">Economic calendar</p>
        <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
          {calendar?.status ?? "WAITING"}
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-400">{calendar?.reason ?? "Waiting for calendar context."}</p>
      <div className="mt-4 space-y-2">
        {rows.length ? rows.map((event) => (
          <MiniLine
            key={`${event.name}-${event.scheduled_at}`}
            label={event.name}
            value={`${formatShortDate(event.scheduled_at)} - ${event.impact}`}
          />
        )) : (
          <p className="rounded-xl bg-white/5 p-3 text-sm text-slate-400">No scheduled high-impact events in the lookahead window.</p>
        )}
      </div>
      {macroEvents.length ? (
        <p className="mt-3 text-xs text-slate-500">
          Macro headline buckets: {macroEvents.slice(0, 3).map((event) => event.event_type).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
