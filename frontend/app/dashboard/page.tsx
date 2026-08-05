"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TodayIntelligence } from "@/lib/types";
import { narrationSource, relativeDate } from "@/lib/format";
import { BreakoutVideo } from "@/components/BreakoutVideo";
import { OpportunityCard } from "@/components/OpportunityCard";
import { TrendCard } from "@/components/TrendCard";
import { EmptyState, SectionHeader, Shell } from "@/components/Shell";

export default function DashboardPage() {
  return (
    <Shell>
      <Dashboard />
    </Shell>
  );
}

function Dashboard() {
  const [data, setData] = useState<TodayIntelligence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.today());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load today's intelligence");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Right after onboarding the pipeline is still running in the background.
  useEffect(() => {
    if (!data || data.opportunities.length || data.breakouts.length) return;
    const timer = setTimeout(load, 4000);
    return () => clearTimeout(timer);
  }, [data, load]);

  async function refresh() {
    setRefreshing(true);
    try {
      await api.refresh();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  if (error) {
    return <EmptyState title="Something went wrong" body={error} />;
  }

  if (!data) {
    return <div className="py-20 text-center text-sm text-neutral-600">Loading…</div>;
  }

  const hasSignal = data.opportunities.length > 0 || data.breakouts.length > 0;
  const narration = narrationSource(data.generated_by);

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="eyebrow">Today&apos;s Intelligence</div>
          <h1 className="mt-2 max-w-2xl text-xl font-semibold leading-snug tracking-tight text-white">
            {data.headline || "Gathering signal from your tracked channels…"}
          </h1>
          <p className="mt-2 text-xs text-neutral-600">
            {data.brief_date} · {data.stats.tracked_channels ?? 0} channels ·{" "}
            {data.stats.window_days ?? 7}-day window
            {data.data_mode.youtube === "seed" ? " · seed data" : ""}
          </p>
        </div>

        <button onClick={refresh} disabled={refreshing} className="btn-ghost">
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* A genuinely quiet niche is a finding, not an error state. Distinct
          from "no data yet", which means we haven't finished collecting. */}
      {data.quiet_day && !hasSignal ? (
        <div className="mt-8">
          <EmptyState
            title="Quiet day"
            body={`Nothing in your niche cleared the bar today. ${
              data.rising_trends.length
                ? "A few topics are moving but haven't proven they perform yet — they're listed below."
                : "No topic is both accelerating and outperforming right now."
            } That's a real answer: stick to what you had planned.`}
          />
        </div>
      ) : !hasSignal ? (
        <div className="mt-8">
          <EmptyState
            title="No signal yet"
            body="We're collecting and analysing your channels. This usually takes under a minute — the page will update on its own."
            action={
              <button onClick={refresh} disabled={refreshing} className="btn-ghost">
                Run it now
              </button>
            }
          />
        </div>
      ) : null}

      {data.opportunities.length ? (
        <section className="mt-10">
          <SectionHeader
            icon="🔥"
            title="Top opportunities"
            caption="Topics that are both accelerating and outperforming across your tracked channels."
          />
          <div className="space-y-3">
            {data.opportunities.map((opportunity, index) => (
              <OpportunityCard key={opportunity.id} opportunity={opportunity} rank={index + 1} />
            ))}
          </div>
        </section>
      ) : null}

      <div className="mt-10 grid gap-10 lg:grid-cols-2">
        {data.breakouts.length ? (
          <section>
            <SectionHeader
              icon="📈"
              title="Breakout content"
              caption="Videos beating their own creator's baseline."
            />
            <div className="space-y-3">
              {data.breakouts.map((breakout) => (
                <BreakoutVideo key={breakout.video_id} breakout={breakout} />
              ))}
            </div>
          </section>
        ) : null}

        {data.rising_trends.length ? (
          <section>
            <SectionHeader
              icon="📊"
              title="Rising trends"
              caption="Ranked by momentum. Click any trend to see the videos behind it."
              action={
                <Link href="/trends" className="text-xs text-neutral-600 hover:text-neutral-300">
                  All trends
                </Link>
              }
            />
            <div className="space-y-3">
              {data.rising_trends.map((trend) => (
                <TrendCard key={trend.trend_id} trend={trend} />
              ))}
            </div>
          </section>
        ) : null}
      </div>

      {data.competitor_activity.length ? (
        <section className="mt-10">
          <SectionHeader
            icon="👀"
            title="Competitor activity"
            caption={`Published in the last ${data.stats.window_days ?? 7} days.`}
            action={
              <Link href="/competitors" className="text-xs text-neutral-600 hover:text-neutral-300">
                All competitors
              </Link>
            }
          />
          <div className="panel divide-y divide-ink-800">
            {data.competitor_activity.map((item, index) => (
              <div key={index} className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4">
                <div className="flex min-w-0 items-center gap-2 sm:contents">
                  <div className="w-24 shrink-0 truncate text-xs text-neutral-500 sm:w-32">
                    {item.channel_name}
                  </div>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-w-0 flex-1 truncate text-sm text-neutral-300 hover:text-white"
                  >
                    {item.title}
                  </a>
                </div>
                <div className="flex shrink-0 items-center justify-end gap-3 sm:contents">
                  {item.subtopic ? (
                    <span className="hidden shrink-0 text-xs text-neutral-600 md:inline">
                      {item.subtopic}
                    </span>
                  ) : null}
                  <span className="w-12 shrink-0 text-right text-xs tabular-nums text-neutral-500 sm:w-16">
                    {item.views_display}
                  </span>
                  <span
                    className={`w-12 shrink-0 text-right text-xs font-medium tabular-nums sm:w-14 ${
                      item.is_breakout ? "text-signal" : "text-neutral-500"
                    }`}
                  >
                    {item.performance}
                  </span>
                  <span className="hidden w-16 shrink-0 text-right text-xs text-neutral-700 sm:inline">
                    {relativeDate(item.published_at)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {narration.degraded ? (
        <p className="mt-10 rounded-lg border border-amber-900/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-200/90">
          {narration.label}
        </p>
      ) : null}

      <p className={`text-xs text-neutral-700 ${narration.degraded ? "mt-3" : "mt-10"}`}>
        Numbers computed from your tracked channels&apos; data.
        {narration.degraded ? "" : ` ${narration.label}`}
      </p>
    </div>
  );
}
