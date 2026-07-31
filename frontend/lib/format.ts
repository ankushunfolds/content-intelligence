export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) >= 1_000_000_000) return trim(value / 1_000_000_000) + "B";
  if (Math.abs(value) >= 1_000_000) return trim(value / 1_000_000) + "M";
  if (Math.abs(value) >= 1_000) return trim(value / 1_000) + "K";
  return String(Math.round(value));
}

function trim(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "");
}

export function multiplier(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  return trim(ratio) + "×";
}

export function percent(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined) return "—";
  const value = fraction * 100;
  return `${value >= 0 ? "+" : ""}${Math.round(value)}%`;
}

export function relativeDate(iso: string): string {
  const then = new Date(iso).getTime();
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

/** Colour a performance ratio by what it means, not by taste. */
export function performanceTone(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "text-neutral-500";
  if (ratio >= 3) return "text-signal";
  if (ratio >= 1.5) return "text-rise";
  if (ratio >= 0.8) return "text-neutral-300";
  return "text-neutral-500";
}

export function scoreTone(score: number): string {
  if (score >= 70) return "text-signal";
  if (score >= 45) return "text-rise";
  return "text-neutral-400";
}
