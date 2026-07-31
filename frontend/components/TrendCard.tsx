import Link from "next/link";
import type { RisingTrend } from "@/lib/types";
import { scoreTone } from "@/lib/format";
import { MomentumBar } from "./Metric";

export function TrendCard({ trend }: { trend: RisingTrend }) {
  return (
    <Link href={`/trends?focus=${trend.trend_id}`} className="panel panel-hover block p-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-neutral-100">
            {trend.subtopic || trend.topic}
          </div>
          <div className="text-xs text-neutral-600">{trend.topic}</div>
        </div>
        <div className={`shrink-0 text-sm font-semibold tabular-nums ${scoreTone(trend.score)}`}>
          {trend.score}
        </div>
      </div>

      <div className="mt-2.5">
        <MomentumBar score={trend.score} />
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
        <span>
          <span className="text-neutral-300">{trend.growth}</span> volume
        </span>
        <span>
          <span className="text-neutral-300">{trend.avg_performance}</span> baseline
        </span>
        <span>
          <span className="text-neutral-300">{trend.creator_count}</span> creators
        </span>
      </div>
    </Link>
  );
}
