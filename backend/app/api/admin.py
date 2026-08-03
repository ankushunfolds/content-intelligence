from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.config import settings
from app.db import get_db
from app.models import Channel, EventLog, User, Video, VideoIntelligence
from app.utils.time import utcnow

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/events")
def events(
    limit: int = Query(100, le=500),
    level: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[dict]:
    """Section 28 — a log view, not a dashboard."""
    query = select(EventLog).order_by(EventLog.created_at.desc()).limit(limit)
    if level:
        query = query.where(EventLog.level == level)
    return [
        {
            "id": e.id,
            "kind": e.kind,
            "level": e.level,
            "message": e.message,
            "duration_ms": e.duration_ms,
            "meta": e.meta,
            "created_at": e.created_at.isoformat(),
        }
        for e in db.scalars(query).all()
    ]


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    return {
        "channels": db.scalar(select(func.count(Channel.id))) or 0,
        "videos": db.scalar(select(func.count(Video.id))) or 0,
        "classified": db.scalar(
            select(func.count(VideoIntelligence.id)).where(VideoIntelligence.topic.is_not(None))
        ) or 0,
        "breakouts": db.scalar(
            select(func.count(VideoIntelligence.id)).where(VideoIntelligence.is_breakout.is_(True))
        ) or 0,
        "errors": db.scalar(select(func.count(EventLog.id)).where(EventLog.level == "error")) or 0,
    }


@router.get("/health-summary")
def health_summary(
    key: str | None = None,
    x_monitor_key: str | None = Header(default=None),
    hours: int = Query(24, le=168),
    db: Session = Depends(get_db),
) -> dict:
    """Unauthenticated-except-for-a-shared-secret error digest, meant for a
    scheduled check to poll — not for the admin UI (that's /events and
    /stats, which require a real login). See Settings.admin_monitor_key.

    404s rather than 401/403 on a bad or missing key so the endpoint doesn't
    announce its own existence to anything scanning for admin routes.

    Prefer the `X-Monitor-Key` header over `?key=`: query strings get written
    verbatim into web-server and platform access logs, so a secret passed that
    way ends up sitting in plaintext in log storage. The query parameter is
    still accepted so existing checks don't break.
    """
    supplied = x_monitor_key or key or ""
    # compare_digest rather than `!=`: a plain string comparison returns as
    # soon as it hits a differing byte, so response time leaks how much of the
    # key a guess got right, which is enough to recover it byte by byte.
    if not settings.admin_monitor_key or not hmac.compare_digest(supplied, settings.admin_monitor_key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    since = utcnow() - timedelta(hours=hours)
    in_window = (EventLog.level == "error", EventLog.created_at >= since)

    # Counted in the database rather than by len() on a fetched page. The old
    # version selected 50 rows and reported that length as error_count, so any
    # incident past 50 errors silently read as exactly 50 — the check would
    # under-report precisely when things were worst.
    error_count = db.scalar(select(func.count(EventLog.id)).where(*in_window)) or 0
    by_kind = dict(
        db.execute(
            select(EventLog.kind, func.count(EventLog.id)).where(*in_window).group_by(EventLog.kind)
        ).all()
    )

    recent = db.scalars(
        select(EventLog).where(*in_window).order_by(EventLog.created_at.desc()).limit(10)
    ).all()

    # Status code is the actionable part of an llm.failure: 404 means a model
    # is gone and needs a deploy, 429 means billing, 503 means wait. Grouping
    # by it turns "15 llm.failure" into an instruction.
    by_status: dict[str, int] = {}
    for event in db.scalars(select(EventLog).where(*in_window)).all():
        code = (event.meta or {}).get("status_code")
        if code is not None:
            by_status[str(code)] = by_status.get(str(code), 0) + 1

    return {
        "since": since.isoformat(),
        "error_count": error_count,
        "errors_by_kind": by_kind,
        "errors_by_status": by_status,
        "recent_errors": [
            {
                "kind": e.kind,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
                "meta": e.meta or {},
            }
            for e in recent
        ],
        "signups_total": db.scalar(select(func.count(User.id))) or 0,
        # Retained for continuity, but note this is not a health signal while
        # email verification is unenforced: users can use the app without it,
        # so a high unverified share means they skipped a step nothing blocks.
        "signups_unverified": db.scalar(select(func.count(User.id)).where(User.is_verified.is_(False))) or 0,
    }
