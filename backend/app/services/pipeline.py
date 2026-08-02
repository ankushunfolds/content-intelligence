"""The full DATA → SIGNALS → INTELLIGENCE → OPPORTUNITIES chain, in order.

Section 16's diagram, expressed as code. Everything that runs on a schedule
(and the manual "refresh" button) goes through here, so there is exactly one
definition of what a complete run means.
"""
from __future__ import annotations

from datetime import date
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, TrackedChannel
from app.services import briefing, classification, ingestion, performance, trends
from app.services.youtube import YouTubeProvider, get_provider
from app.utils.logging import record_event


def user_channels(db: Session, user_id: int) -> list[Channel]:
    return list(
        db.scalars(
            select(Channel)
            .join(TrackedChannel, TrackedChannel.channel_id == Channel.id)
            .where(TrackedChannel.user_id == user_id)
        ).all()
    )


def run_pipeline(
    db: Session,
    user_id: int,
    *,
    provider: YouTubeProvider | None = None,
    skip_ingestion: bool = False,
) -> dict:
    """Run every stage for one user and return a summary of what changed."""
    started = perf_counter()
    provider = provider or get_provider()

    channels = user_channels(db, user_id)
    if not channels:
        return {
            "channels_ingested": 0,
            "videos_ingested": 0,
            "videos_classified": 0,
            "trends_detected": 0,
            "breakouts_detected": 0,
            "brief_date": None,
            "duration_seconds": 0.0,
        }

    # 1. DATA — pull raw facts from YouTube.
    ingest_result = {"channels": 0, "new_videos": 0}
    if not skip_ingestion:
        ingest_result = ingestion.ingest_channels(db, channels, provider)

    # 2. SIGNALS — deterministic performance maths (must precede trends).
    perf_result = performance.score_channels(db, channels)

    # 3. INTELLIGENCE — semantic classification, only for unclassified videos,
    #    and capped per run so one big onboarding can't burn a day's LLM quota
    #    in a single request. The remainder is picked up next run.
    classified = classification.classify_pending(db, channels, limit=settings.max_classify_per_run)

    # 4. TREND ENGINE — aggregate classified + scored videos.
    detected = trends.compute_trends(db, user_id)

    # 5. BRIEF — select signals, then narrate them.
    brief = briefing.generate_brief(db, user_id, force=True)

    duration = perf_counter() - started
    summary = {
        "channels_ingested": ingest_result["channels"],
        "videos_ingested": ingest_result["new_videos"],
        "videos_classified": classified,
        "trends_detected": len(detected),
        "breakouts_detected": perf_result["breakouts"],
        "brief_date": brief.brief_date,
        "duration_seconds": round(duration, 2),
    }
    record_event(db, "pipeline.run", f"user {user_id}: {summary}", duration_ms=duration * 1000, **{
        k: (v.isoformat() if isinstance(v, date) else v) for k, v in summary.items()
    })
    return summary
