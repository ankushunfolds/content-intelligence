"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Brief } from "@/lib/types";
import { relativeDate } from "@/lib/format";
import { BreakoutVideo } from "@/components/BreakoutVideo";
import { OpportunityCard } from "@/components/OpportunityCard";
import { EmptyState, SectionHeader, Shell } from "@/components/Shell";

export default function BriefsPage() {
  return (
    <Shell>
      <Briefs />
    </Shell>
  );
}

function Briefs() {
  const [briefs, setBriefs] = useState<Brief[] | null>(null);
  const [selected, setSelected] = useState<Brief | null>(null);

  useEffect(() => {
    api.briefs().then((rows) => {
      setBriefs(rows);
      setSelected(rows[0] || null);
    });
  }, []);

  if (briefs === null) return <p className="text-sm text-neutral-600">Loading…</p>;

  if (!briefs.length) {
    return (
      <EmptyState
        title="No briefs yet"
        body="Your first brief is generated once your channels have been collected and analysed. Trigger it from the dashboard."
      />
    );
  }

  return (
    <div>
      <div className="eyebrow">Daily brief</div>
      <h1 className="mt-2 text-xl font-semibold tracking-tight text-white">Brief archive</h1>

      <div className="mt-8 grid gap-6 lg:grid-cols-[220px_1fr]">
        <div className="space-y-1.5">
          {briefs.map((brief) => (
            <button
              key={brief.id}
              onClick={() => setSelected(brief)}
              className={`w-full rounded-lg px-3 py-2 text-left transition-colors ${
                selected?.id === brief.id
                  ? "bg-ink-800 text-white"
                  : "text-neutral-500 hover:bg-ink-900 hover:text-neutral-300"
              }`}
            >
              <div className="text-sm font-medium">{brief.brief_date}</div>
              <div className="text-[11px] text-neutral-600">
                {relativeDate(brief.created_at)} ·{" "}
                {brief.content.opportunities?.length ?? 0} opportunities
              </div>
            </button>
          ))}
        </div>

        {selected ? <BriefDetail brief={selected} /> : null}
      </div>
    </div>
  );
}

function BriefDetail({ brief }: { brief: Brief }) {
  const { content } = brief;

  return (
    <div>
      <div className="panel p-5">
        <div className="eyebrow">{brief.brief_date}</div>
        <h2 className="mt-2 text-base font-semibold leading-snug text-white">{content.headline}</h2>
      </div>

      {content.opportunities?.length ? (
        <section className="mt-8">
          <SectionHeader icon="🔥" title="Top opportunities" />
          <div className="space-y-3">
            {content.opportunities.map((opportunity, index) => (
              <OpportunityCard key={opportunity.id} opportunity={opportunity} rank={index + 1} />
            ))}
          </div>
        </section>
      ) : null}

      {content.competitor_highlights?.length ? (
        <section className="mt-8">
          <SectionHeader icon="📈" title="Competitor highlights" />
          <div className="space-y-3">
            {content.competitor_highlights.map((breakout) => (
              <BreakoutVideo key={breakout.video_id} breakout={breakout} />
            ))}
          </div>
        </section>
      ) : null}

      {content.rising_trends?.length ? (
        <section className="mt-8">
          <SectionHeader icon="📊" title="Rising trends" />
          <div className="panel divide-y divide-ink-800">
            {content.rising_trends.map((trend) => (
              <div
                key={trend.trend_id}
                className="flex items-center gap-2 px-4 py-2.5 text-sm sm:gap-4"
              >
                <span className="min-w-0 flex-1 truncate text-neutral-200">
                  {trend.subtopic || trend.topic}
                </span>
                <span className="hidden shrink-0 text-right text-xs tabular-nums text-neutral-500 sm:inline sm:w-16">
                  {trend.growth}
                </span>
                <span className="w-12 shrink-0 text-right text-xs tabular-nums text-neutral-500 sm:w-16">
                  {trend.avg_performance}
                </span>
                <span className="w-10 shrink-0 text-right font-semibold tabular-nums text-neutral-200">
                  {trend.score}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <p className="mt-8 text-xs text-neutral-700">
        Generated {new Date(content.generated_at).toLocaleString()} · numbers from the database,
        wording by {brief.generated_by}.
      </p>
    </div>
  );
}
