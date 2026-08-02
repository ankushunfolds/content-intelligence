from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    key: str,
    hours: int = Query(24, le=168),
    db: Session = Depends(get_db),
) -> dict:
    """Unauthenticated-except-for-a-shared-secret error digest, meant for a
    scheduled check to poll — not for the admin UI (that's /events and
    /stats, which require a real login). See Settings.admin_monitor_key.

    404s rather than 401/403 on a bad or missing key so the endpoint doesn't
    announce its own existence to anything scanning for admin routes.
    """
    if not settings.admin_monitor_key or key != settings.admin_monitor_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    since = utcnow() - timedelta(hours=hours)
    errors = db.scalars(
        select(EventLog)
        .where(EventLog.level == "error", EventLog.created_at >= since)
        .order_by(EventLog.created_at.desc())
        .limit(50)
    ).all()

    by_kind: dict[str, int] = {}
    for e in errors:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1

    return {
        "since": since.isoformat(),
        "error_count": len(errors),
        "errors_by_kind": by_kind,
        "recent_errors": [
            {"kind": e.kind, "message": e.message, "created_at": e.created_at.isoformat()}
            for e in errors[:10]
        ],
        "signups_total": db.scalar(select(func.count(User.id))) or 0,
        "signups_unverified": db.scalar(select(func.count(User.id)).where(User.is_verified.is_(False))) or 0,
    }
