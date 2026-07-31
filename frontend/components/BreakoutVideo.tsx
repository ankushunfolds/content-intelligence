import type { Breakout } from "@/lib/types";
import { relativeDate } from "@/lib/format";

/** A video outperforming its own creator's baseline — never ranked on raw views. */
export function BreakoutVideo({ breakout }: { breakout: Breakout }) {
  return (
    <article className="panel panel-hover p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs text-neutral-500">
            {breakout.channel_name} · {relativeDate(breakout.published_at)}
          </div>
          <a
            href={breakout.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 block truncate text-sm font-medium text-neutral-100 hover:text-white"
          >
            {breakout.title}
          </a>
        </div>

        <div className="shrink-0 text-right">
          <div className="text-lg font-semibold tabular-nums text-signal">{breakout.performance}</div>
          <div className="text-[11px] text-neutral-600">baseline</div>
        </div>
      </div>

      <p className="mt-2.5 text-xs leading-relaxed text-neutral-400">{breakout.why_it_matters}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="chip">{breakout.views_display} views</span>
        <span className="chip">usual {breakout.baseline_display}</span>
        {breakout.subtopic ? <span className="chip">{breakout.subtopic}</span> : null}
        {breakout.format ? <span className="chip">{breakout.format}</span> : null}
      </div>
    </article>
  );
}
