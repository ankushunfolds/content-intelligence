from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import get_db
from app.models import Channel, EventLog, User, Video, VideoIntelligence

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
