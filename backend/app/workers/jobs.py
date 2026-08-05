"""Section 21 — the four background jobs, each runnable on its own.

They're thin wrappers over the services so that a job never contains business
logic (Rule 4). Every one is idempotent: re-running costs little and breaks nothing.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Channel, User
from app.services import briefing, classification, ingestion, performance, trends
from app.services.email import EmailError, send_brief_email
from app.services.pipeline import user_channels
from app.services.youtube import get_provider
from app.utils.logging import logger, record_event
from app.utils.security import create_unsubscribe_token
from app.utils.time import utcnow


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
    """Job 4 — one brief per user per day, emailed if there's anything to say."""
    db = SessionLocal()
    try:
        generated = 0
        emailed = 0
        for user in db.scalars(select(User)).all():
            if not user_channels(db, user.id):
                continue
            brief = briefing.generate_brief(db, user.id, force=True)
            generated += 1
            if _email_brief(db, user, brief):
                emailed += 1
        record_event(db, "job.briefs", f"{generated} briefs generated, {emailed} emailed")
        return {"briefs": generated, "emailed": emailed}
    finally:
        db.close()


def _email_brief(db, user: User, brief) -> bool:
    """Send the brief, unless there's a reason not to. Returns whether it sent.

    Four gates, in cheapest-first order. The quiet-day one is the interesting
    one: an email that arrives every single day whether or not it has anything
    to say is how a daily product teaches people to ignore it. Silence is what
    keeps the other mornings worth opening.
    """
    content = brief.content if isinstance(brief.content, dict) else {}

    if not user.email_briefs:
        return False
    if content.get("quiet_day") or not content.get("opportunities"):
        return False
    if brief.generated_by in briefing.FALLBACK_SOURCES:
        # Template prose is fine to show someone who came looking. Pushing it
        # into their inbox as today's analysis is a different promise.
        logger.info("skipping brief email for user %s — narration is %s", user.id, brief.generated_by)
        return False
    if user.brief_emailed_on and user.brief_emailed_on.date() == brief.brief_date:
        return False  # the job already ran today

    try:
        send_brief_email(user.email, content, create_unsubscribe_token(user.id))
    except EmailError as exc:
        record_event(db, "email.failure", f"brief email to user {user.id}: {exc}", level="error", user_id=user.id)
        return False

    user.brief_emailed_on = utcnow()
    db.add(user)
    db.commit()
    return True


def run_daily_cycle() -> dict:
    """All four, in the only order that makes sense."""
    return {
        "ingest": job_ingest_channels(),
        "analyse": job_analyse_videos(),
        "trends": job_compute_trends(),
        "briefs": job_generate_briefs(),
    }
