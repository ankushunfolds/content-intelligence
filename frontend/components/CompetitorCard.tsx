"use client";

import Link from "next/link";
import type { TrackedChannel } from "@/lib/types";
import { compact, relativeDate } from "@/lib/format";

export function CompetitorCard({
  channel,
  onRemove,
}: {
  channel: TrackedChannel;
  onRemove?: (channelId: number) => void;
}) {
  return (
    <article className="panel panel-hover p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link
              href={`/competitors/${channel.id}`}
              className="truncate text-sm font-semibold text-neutral-100 hover:text-white"
            >
              {channel.name}
            </Link>
            {channel.type === "own" ? (
              <span className="rounded bg-signal/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-signal">
                You
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 text-xs text-neutral-500">
            {compact(channel.subscriber_count)} subscribers
            {channel.last_upload_at ? ` · last upload ${relativeDate(channel.last_upload_at)}` : ""}
          </div>
        </div>

        {onRemove && channel.type !== "own" ? (
          <button
            onClick={() => onRemove(channel.id)}
            className="shrink-0 text-xs text-neutral-600 hover:text-fall"
            aria-label={`Stop tracking ${channel.name}`}
          >
            Remove
          </button>
        ) : null}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 border-t border-ink-800 pt-3">
        <Stat label="Median views" value={compact(channel.median_views)} />
        <Stat label="Last 30d" value={`${channel.videos_last_30d} videos`} />
        <Stat
          label="Cadence"
          value={channel.upload_cadence_days ? `${channel.upload_cadence_days}d` : "—"}
        />
      </div>

      {channel.breakouts_last_30d > 0 ? (
        <div className="mt-3 text-xs text-signal">
          {channel.breakouts_last_30d} breakout{channel.breakouts_last_30d > 1 ? "s" : ""} in the last 30
          days
        </div>
      ) : null}

      {channel.top_topics.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {channel.top_topics.map((topic) => (
            <span key={topic} className="chip">
              {topic}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-600">{label}</div>
      <div className="mt-0.5 text-sm font-medium tabular-nums text-neutral-200">{value}</div>
    </div>
  );
}
