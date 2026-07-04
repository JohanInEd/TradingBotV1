export function isFiniteNumber(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value));
}

export function paddedDomain(values, padding = 0.1) {
  const finite = values.filter(isFiniteNumber);
  if (!finite.length) return [0, 1];
  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (min === max) {
    min -= Math.max(1, Math.abs(min) * 0.01);
    max += Math.max(1, Math.abs(max) * 0.01);
  }
  const pad = (max - min) * padding;
  return [min - pad, max + pad];
}

export function seriesPath(rows, key, xFor, yFor) {
  const points = rows
    .map((row, index) => [xFor(index), row[key]])
    .filter(([, value]) => isFiniteNumber(value));
  if (!points.length) return "";
  return points
    .map(([x, value], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${yFor(value).toFixed(2)}`)
    .join(" ");
}

export function pathFromPoints(rows, xFor, yFor) {
  const points = rows
    .map((row, index) => [xFor(index), row.price])
    .filter(([, value]) => isFiniteNumber(value));
  if (!points.length) return "";
  return points
    .map(([x, value], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${yFor(value).toFixed(2)}`)
    .join(" ");
}

export function connectionClass(connection) {
  if (connection === "live") return "bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.8)]";
  if (connection === "reconnecting") return "bg-amber-300";
  if (connection === "offline") return "bg-rose-400";
  return "bg-cyan-300";
}

export function formatUsd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2
  }).format(Number(value));
}

export function formatCompactUsd(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const amount = Number(value);
  if (Math.abs(amount) >= 1_000_000_000) return `$${(amount / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(amount) >= 1_000_000) return `$${(amount / 1_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000) return `$${(amount / 1_000).toFixed(2)}K`;
  return formatUsd(amount);
}

export function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const amount = Number(value);
  if (Math.abs(amount) >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(amount) >= 1_000_000) return `${(amount / 1_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000) return `${(amount / 1_000).toFixed(2)}K`;
  return amount.toFixed(2);
}

export function formatPct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}%`;
}

export function formatProbability(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(0)}%`;
}

export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

export function formatSignedNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

export function formatRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${Number(value).toFixed(1)}x`;
}

export function formatAgeSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const seconds = Math.max(0, Number(value));
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

export function formatTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}

export function formatShortDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit"
  }).format(new Date(value));
}

export function timeframeHoursFor(timeframe) {
  const match = String(timeframe ?? "4h").trim().toLowerCase().match(/^(\d+(?:\.\d+)?)([mhd])$/);
  if (!match) return 4;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return 4;
  if (match[2] === "m") return value / 60;
  if (match[2] === "h") return value;
  if (match[2] === "d") return value * 24;
  return 4;
}

export function candlesPerDayFor(timeframe) {
  return Math.max(1, Math.round(24 / timeframeHoursFor(timeframe)));
}

export function scenarioHorizonLabel(horizonHours) {
  const hours = Number(horizonHours);
  if (!Number.isFinite(hours) || hours <= 0) return "7d";
  if (hours % 24 === 0) return `${hours / 24}d`;
  return `${hours}h`;
}

export function trendState(candle) {
  if (!isFiniteNumber(candle?.ema20) || !isFiniteNumber(candle?.ema50)) return "flat";
  if (candle.ema20 > candle.ema50 && candle.close >= candle.ema20) return "up";
  if (candle.ema20 < candle.ema50 && candle.close <= candle.ema20) return "down";
  return "flat";
}

export function trendLabel(candle) {
  const state = trendState(candle);
  if (state === "up") return "trend up";
  if (state === "down") return "trend down";
  return "range";
}

export function tradeFilterTone(tradeFilter) {
  if (tradeFilter?.status === "PASS") return "positive";
  if (tradeFilter?.status === "BLOCKED") return "negative";
  if (tradeFilter?.status === "NO SETUP") return "neutral";
  return "warning";
}

export function confidenceTone(confidence) {
  if (confidence?.label === "HIGH") return "positive";
  if (confidence?.label === "MEDIUM") return "neutral";
  if (confidence?.label === "LOW") return "warning";
  return "neutral";
}

export function confidenceTextClass(confidence) {
  if (confidence?.label === "HIGH") return "text-emerald-300";
  if (confidence?.label === "MEDIUM") return "text-cyan-200";
  if (confidence?.label === "LOW") return "text-amber-200";
  return "text-slate-100";
}

export function confidenceBadgeClass(confidence) {
  if (confidence?.label === "HIGH") return "border-emerald-300/30 bg-emerald-300/10 text-emerald-100";
  if (confidence?.label === "MEDIUM") return "border-cyan-300/30 bg-cyan-300/10 text-cyan-100";
  if (confidence?.label === "LOW") return "border-amber-300/30 bg-amber-300/10 text-amber-100";
  return "border-white/10 bg-white/5 text-slate-300";
}

export function scannerActionClass(action) {
  if (action === "GO LONG") return "bg-emerald-300/15 text-emerald-200";
  if (action === "GO SHORT") return "bg-rose-300/15 text-rose-200";
  if (action === "STAY FLAT") return "bg-cyan-300/15 text-cyan-100";
  return "bg-white/10 text-slate-300";
}

export function portfolioStatusClass(status) {
  if (!status) return "bg-white/10 text-slate-400";
  if (status === "RECORDED" || status === "ALLOWED") return "bg-emerald-300/15 text-emerald-200";
  if (status === "TRACKED" || status === "PRIMARY") return "bg-cyan-300/15 text-cyan-100";
  if (status.startsWith("BLOCKED")) return "bg-rose-300/15 text-rose-200";
  return "bg-white/10 text-slate-300";
}

export function driftToneClass(status) {
  if (status === "ALERT") return "border-rose-300/30 bg-rose-300/10 text-rose-100";
  if (status === "WARNING") return "border-amber-300/30 bg-amber-300/10 text-amber-100";
  if (status === "NORMAL") return "border-emerald-300/30 bg-emerald-300/10 text-emerald-100";
  return "border-white/10 bg-white/5 text-slate-300";
}

export function shakeoutSignalContext(shakeout, signal) {
  if (!shakeout) return "Waiting for context";
  if (shakeout.status === "CALM") return "Context only";
  const mainSignal = signal?.signal ?? "HOLD / NEUTRAL";
  const riskSide = shakeout.direction?.includes("UPSIDE")
    ? "BUY"
    : shakeout.direction?.includes("DOWNSIDE")
      ? "SELL"
      : null;
  if (!riskSide) return `Context only; two-sided while signal is ${mainSignal}`;
  if (mainSignal === "STRONG BUY" && riskSide === "BUY") {
    return "Context only; agrees with signal";
  }
  if (mainSignal === "STRONG SELL" && riskSide === "SELL") {
    return "Context only; agrees with signal";
  }
  if (mainSignal === "STRONG BUY" || mainSignal === "STRONG SELL") {
    return "Context only; conflicts with signal";
  }
  return "Context only; neutral signal";
}
