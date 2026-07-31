/**
 * A number never appears alone. Every metric carries a label and, where it
 * exists, the context that answers "so what?" (Section 23).
 */
export function Metric({
  label,
  value,
  context,
  tone = "text-neutral-100",
  size = "md",
}: {
  label: string;
  value: string;
  context?: string;
  tone?: string;
  size?: "sm" | "md" | "lg";
}) {
  const valueSize = { sm: "text-base", md: "text-xl", lg: "text-3xl" }[size];
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className={`mt-1 font-semibold tabular-nums ${valueSize} ${tone}`}>{value}</div>
      {context ? <div className="mt-0.5 text-xs text-neutral-500">{context}</div> : null}
    </div>
  );
}

export function MomentumBar({ score }: { score: number }) {
  const tone = score >= 70 ? "bg-signal" : score >= 45 ? "bg-rise" : "bg-ink-600";
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-ink-700">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(2, score)}%` }} />
    </div>
  );
}
