"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TrackedChannel, Video } from "@/lib/types";
import { compact, multiplier, performanceTone, relativeDate } from "@/lib/format";
import { Metric } from "@/components/Metric";
import { EmptyState, Shell } from "@/components/Shell";

type Sort = "performance" | "recent" | "views";

export default function ChannelPage() {
  return (
    <Shell>
      <ChannelDetail />
    </Shell>
  );
}

function ChannelDetail() {
  const params = useParams<{ id: string }>();
  const channelId = Number(params.id);

  const [channel, setChannel] = useState<TrackedChannel | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [sort, setSort] = useState<Sort>("performance");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.channel(channelId).then(setChannel).catch((err) => setError(err.message));
  }, [channelId]);

  useEffect(() => {
    api.channelVideos(channelId, sort).then(setVideos).catch(() => setVideos([]));
  }, [channelId, sort]);

  if (error) return <EmptyState title="Channel not found" body={error} />;
  if (!channel) return <p className="text-sm text-neutral-600">Loading…</p>;

  return (
    <div>
      <Link href="/competitors" className="text-xs text-neutral-600 hover:text-neutral-300">
        ← Competitors
      </Link>

      <h1 className="mt-4 text-xl font-semibold tracking-tight text-white">{channel.name}</h1>
      <p className="mt-1 text-xs text-neutral-600">
        {compact(channel.subscriber_count)} subscribers · {compact(channel.total_views)} total views
        {channel.last_upload_at ? ` · last upload ${relativeDate(channel.last_upload_at)}` : ""}
      </p>

      <div className="panel mt-6 grid grid-cols-2 gap-6 p-5 sm:grid-cols-4">
        <Metric
          label="Median views"
          value={compact(channel.median_views)}
          context="the baseline every video is scored against"
        />
        <Metric label="Videos / 30d" value={String(channel.videos_last_30d)} />
        <Metric
          label="Cadence"
          value={channel.upload_cadence_days ? `${channel.upload_cadence_days} days` : "—"}
          context="typical gap between uploads"
        />
        <Metric
          label="Breakouts / 30d"
          value={String(channel.breakouts_last_30d)}
          tone={channel.breakouts_last_30d ? "text-signal" : "text-neutral-100"}
          context="3× baseline or better"
        />
      </div>

      <div className="mt-8 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-neutral-200">Videos</h2>
        <div className="flex gap-1">
          {(["performance", "recent", "views"] as Sort[]).map((option) => (
            <button
              key={option}
              onClick={() => setSort(option)}
              className={`rounded-md px-2.5 py-1 text-xs capitalize transition-colors ${
                sort === option ? "bg-ink-800 text-white" : "text-neutral-600 hover:text-neutral-300"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="panel mt-3 divide-y divide-ink-800">
        {videos.map((video) => {
          const intel = video.intelligence;
          return (
            <div key={video.id} className="px-4 py-3">
              <div className="flex items-start gap-4">
                <div className="min-w-0 flex-1">
                  <a
                    href={video.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block truncate text-sm text-neutral-200 hover:text-white"
                  >
                    {video.title}
                  </a>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-neutral-600">
                    <span>{relativeDate(video.published_at)}</span>
                    {intel?.subtopic ? <span className="chip">{intel.subtopic}</span> : null}
                    {intel?.format ? <span className="chip">{intel.format}</span> : null}
                    {intel?.is_breakout ? (
                      <span className="rounded bg-signal/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-signal">
                        Breakout
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="shrink-0 text-right">
                  <div className="text-sm font-medium tabular-nums text-neutral-200">
                    {compact(video.views)}
                  </div>
                  <div
                    className={`text-xs font-medium tabular-nums ${performanceTone(
                      intel?.performance_ratio
                    )}`}
                  >
                    {multiplier(intel?.performance_ratio)} baseline
                  </div>
                </div>
              </div>
            </div>
          );
        })}

        {!videos.length ? (
          <p className="px-4 py-8 text-center text-sm text-neutral-600">
            No videos ingested yet for this channel.
          </p>
        ) : null}
      </div>
    </div>
  );
}
