"""Section 21 — the four background jobs, each runnable on its own.

They're thin wrappers over the services so that a job never contains business
logic (Rule 4). Every one is idempotent: re-running costs little and breaks nothing.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Channel, User
from app.services import briefing, classification, ingestion, performance, trends
from app.services.pipeline import user_channels
from app.services.youtube import get_provider
from app.utils.logging import record_event


def job_ingest_channels() -> dict:
    """Job 1 — fetch new videos and refresh metrics for every known channel."""
    db = SessionLocal()
    try:
        channels = list(db.scalars(select(Channel)).all())
        result = ingestion.ingest_channels(db, channels, get_provider())
        record_event(db, "job.ingest", f"{result['channels']} channels, {result['new_videos']} new videos")
        return result
    finally:
        db.close()


def job_analyse_videos() -> dict:
    """Job 2 — score performance, then classify anything unclassified."""
    db = SessionLocal()
    try:
        channels = list(db.scalars(select(Channel)).all())
        perf = performance.score_channels(db, channels)
        classified = classification.classify_pending(db, channels)
        record_event(db, "job.analyse", f"{perf['videos_scored']} scored, {classified} classified")
        return {**perf, "classified": classified}
    finally:
        db.close()


def job_compute_trends() -> dict:
    """Job 3 — recompute trend scores per user."""
    db = SessionLocal()
    try:
        total = 0
        for user in db.scalars(select(User)).all():
            total += len(trends.compute_trends(db, user.id))
        record_event(db, "job.trends", f"{total} trends across all users")
        return {"trends": total}
    finally:
        db.close()


def job_generate_briefs() -> dict:
    """Job 4 — one brief per user per day."""
    db = SessionLocal()
    try:
        generated = 0
        for user in db.scalars(select(User)).all():
            if not user_channels(db, user.id):
                continue
            briefing.generate_brief(db, user.id, force=True)
            generated += 1
        record_event(db, "job.briefs", f"{generated} briefs generated")
        return {"briefs": generated}
    finally:
        db.close()


def run_daily_cycle() -> dict:
    """All four, in the only order that makes sense."""
    return {
        "ingest": job_ingest_channels(),
        "analyse": job_analyse_videos(),
        "trends": job_compute_trends(),
        "briefs": job_generate_briefs(),
    }
