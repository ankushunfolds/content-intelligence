"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Trend, Video } from "@/lib/types";
import { compact, multiplier, percent, performanceTone, relativeDate, scoreTone } from "@/lib/format";
import { MomentumBar } from "@/components/Metric";
import { EmptyState, Shell } from "@/components/Shell";

export default function TrendsPage() {
  return (
    <Shell>
      <Trends />
    </Shell>
  );
}

function Trends() {
  const [trends, setTrends] = useState<Trend[] | null>(null);
  const [selected, setSelected] = useState<Trend | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);

  useEffect(() => {
    api.trends().then((rows) => {
      setTrends(rows);
      const focus = new URLSearchParams(window.location.search).get("focus");
      const initial = (focus && rows.find((t) => t.id === Number(focus))) || rows[0] || null;
      setSelected(initial);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.trendVideos(selected.id).then(setVideos).catch(() => setVideos([]));
  }, [selected]);

  if (trends === null) return <p className="text-sm text-neutral-600">Loading…</p>;

  if (!trends.length) {
    return (
      <EmptyState
        title="No trends detected yet"
        body="A trend needs at least a few videos on the same topic across your tracked channels inside the detection window. Add more competitors, or refresh from the dashboard."
      />
    );
  }

  return (
    <div>
      <div className="eyebrow">Trend engine</div>
      <h1 className="mt-2 text-xl font-semibold tracking-tight text-white">
        What&apos;s moving in your niche
      </h1>
      <p className="mt-2 max-w-2xl text-sm text-neutral-500">
        A trend is a topic appearing more often <em>and</em> outperforming its creators&apos; normal
        content. Every score below is deterministic — select one to see how it was built.
      </p>

      <div className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="space-y-2">
          {trends.map((trend) => (
            <button
              key={trend.id}
              onClick={() => setSelected(trend)}
              className={`panel w-full p-3 text-left transition-colors ${
                selected?.id === trend.id ? "border-signal/50 bg-ink-800" : "panel-hover"
              }`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-sm text-neutral-100">
                  {trend.subtopic || trend.topic}
                </span>
                <span className={`text-sm font-semibold tabular-nums ${scoreTone(trend.trend_score)}`}>
                  {trend.trend_score}
                </span>
              </div>
              <div className="mt-2">
                <MomentumBar score={trend.trend_score} />
              </div>
            </button>
          ))}
        </div>

        {selected ? <TrendDetail trend={selected} videos={videos} /> : null}
      </div>
    </div>
  );
}

function TrendDetail({ trend, videos }: { trend: Trend; videos: Video[] }) {
  const signals = trend.components.signals || {};

  return (
    <div>
      <div className="panel p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-white">{trend.subtopic || trend.topic}</h2>
            <p className="mt-0.5 text-xs text-neutral-600">
              {trend.topic}
              {trend.top_format ? ` · ${trend.top_format} is the dominant format` : ""}
            </p>
          </div>
          <div className="text-right">
            <div className={`text-3xl font-semibold tabular-nums ${scoreTone(trend.trend_score)}`}>
              {trend.trend_score}
            </div>
            <div className="text-[11px] text-neutral-600">trend score</div>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 border-t border-ink-800 pt-4 sm:grid-cols-4">
          <Fact label="Volume growth" value={percent(trend.volume_growth)} />
          <Fact label="Avg performance" value={multiplier(trend.avg_performance)} />
          <Fact label="Creators" value={String(trend.creator_count)} />
          <Fact label="Breakouts" value={String(trend.breakout_count)} />
        </div>

        <div className="mt-5 border-t border-ink-800 pt-4">
          <div className="eyebrow mb-3">How this score was built</div>
          <div className="space-y-2">
            {Object.entries(signals).map(([signal, part]) => (
              <div key={signal} className="flex items-center gap-2 text-xs sm:gap-3">
                <span className="w-16 shrink-0 truncate capitalize text-neutral-400 sm:w-32">
                  {signal.replace(/_/g, " ")}
                </span>
                <div className="h-1.5 min-w-4 flex-1 overflow-hidden rounded-full bg-ink-700">
                  <div
                    className="h-full rounded-full bg-neutral-500"
                    style={{ width: `${part.normalised * 100}%` }}
                  />
                </div>
                <span className="hidden shrink-0 text-right tabular-nums text-neutral-600 sm:inline sm:w-20">
                  ×{part.weight}
                </span>
                <span className="w-12 shrink-0 text-right tabular-nums text-neutral-200">
                  +{part.contribution}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-neutral-600">
            {trend.components.recent_videos} videos in the last {trend.components.window_days} days
            versus {trend.components.prior_videos} in the window before it.
          </p>
        </div>
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold text-neutral-200">The evidence</h3>
        <p className="mt-0.5 text-xs text-neutral-600">
          Every video this trend was computed from, best-performing first.
        </p>

        <div className="panel mt-3 divide-y divide-ink-800">
          {videos.map((video) => (
            <div
              key={video.id}
              className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4"
            >
              <div className="flex min-w-0 items-center gap-2 sm:contents">
                <span className="w-16 shrink-0 truncate text-xs text-neutral-600 sm:w-28">
                  {video.channel_name}
                </span>
                <a
                  href={video.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate text-sm text-neutral-300 hover:text-white"
                >
                  {video.title}
                </a>
              </div>
              <div className="flex shrink-0 items-center justify-end gap-3 sm:contents">
                <span className="w-14 shrink-0 text-right text-xs tabular-nums text-neutral-500">
                  {compact(video.views)}
                </span>
                <span
                  className={`w-14 shrink-0 text-right text-xs font-medium tabular-nums ${performanceTone(
                    video.intelligence?.performance_ratio
                  )}`}
                >
                  {multiplier(video.intelligence?.performance_ratio)}
                </span>
                <span className="hidden w-14 shrink-0 text-right text-xs text-neutral-700 sm:inline">
                  {relativeDate(video.published_at)}
                </span>
              </div>
            </div>
          ))}
          {!videos.length ? (
            <p className="px-4 py-6 text-center text-sm text-neutral-600">No videos to show.</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-600">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-neutral-100">{value}</div>
    </div>
  );
}
