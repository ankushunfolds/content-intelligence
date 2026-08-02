"use client";

import { useState } from "react";
import type { Opportunity } from "@/lib/types";
import { scoreTone } from "@/lib/format";
import { MomentumBar } from "./Metric";

/**
 * The unit of the product: a topic, why it matters, and what to do about it.
 * The evidence is always one click away — a recommendation you can't interrogate
 * is just an opinion (Section 26).
 */
export function OpportunityCard({ opportunity, rank }: { opportunity: Opportunity; rank: number }) {
  const [showEvidence, setShowEvidence] = useState(false);
  const { evidence, score_breakdown } = opportunity;

  return (
    <article className="panel p-5">
      <div className="flex items-start gap-4">
        <div className="mt-0.5 w-5 shrink-0 text-sm font-semibold tabular-nums text-neutral-600">
          {rank}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="text-base font-semibold text-white">
              {opportunity.subtopic || opportunity.topic}
            </h3>
            <div className={`text-sm font-semibold tabular-nums ${scoreTone(opportunity.momentum)}`}>
              {opportunity.momentum}
              <span className="text-neutral-600">/100</span>
            </div>
          </div>

          <div className="mt-2">
            <MomentumBar score={opportunity.momentum} />
          </div>

          <p className="mt-3 text-sm leading-relaxed text-neutral-300">{opportunity.why_it_matters}</p>

          <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/60 p-3">
            <div className="eyebrow">Possible direction</div>
            <p className="mt-1 text-sm font-medium text-neutral-100">
              &ldquo;{opportunity.suggested_direction}&rdquo;
            </p>
            {opportunity.top_format ? (
              <p className="mt-1.5 text-xs text-neutral-500">
                {opportunity.top_format} is the format currently working for this topic.
              </p>
            ) : null}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="chip">{evidence.creator_count} creators</span>
            <span className="chip">{evidence.video_count} videos</span>
            <span className="chip">{evidence.volume_growth_pct} volume</span>
            <span className="chip">{evidence.avg_performance} baseline</span>
            <button
              onClick={() => setShowEvidence((open) => !open)}
              className="ml-auto text-xs text-neutral-500 underline-offset-2 hover:text-neutral-300 hover:underline"
            >
              {showEvidence ? "Hide" : "How was this scored?"}
            </button>
          </div>

          {showEvidence ? (
            <div className="mt-3 rounded-lg border border-ink-700 bg-ink-950/60 p-3">
              <div className="eyebrow mb-2">Score breakdown</div>
              <div className="space-y-1.5">
                {Object.entries(score_breakdown || {}).map(([signal, part]) => (
                  <div key={signal} className="flex items-center gap-2 text-xs sm:gap-3">
                    <span className="w-16 shrink-0 truncate capitalize text-neutral-400 sm:w-32">
                      {signal.replace(/_/g, " ")}
                    </span>
                    <div className="h-1 min-w-4 flex-1 overflow-hidden rounded-full bg-ink-700">
                      <div
                        className="h-full bg-neutral-500"
                        style={{ width: `${(part.normalised || 0) * 100}%` }}
                      />
                    </div>
                    <span className="hidden shrink-0 text-right tabular-nums text-neutral-500 sm:inline sm:w-24">
                      raw {part.raw}
                    </span>
                    <span className="w-14 shrink-0 text-right tabular-nums text-neutral-300">
                      +{part.contribution}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-2.5 text-[11px] leading-relaxed text-neutral-600">
                Computed in the database over the last {evidence.window_days} days. The model wrote the
                explanation; it did not produce any of these numbers.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
}
