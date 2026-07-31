from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import Channel, TrackedChannel, Trend, User, Video, VideoIntelligence
from app.schemas import TrendOut, VideoOut
from app.services import trends as trend_service
from app.api.videos import _to_out

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("", response_model=list[TrendOut])
def list_trends(
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[Trend]:
    return trend_service.top_trends(db, user.id, limit)


@router.post("/recompute", response_model=list[TrendOut])
def recompute(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Trend]:
    return trend_service.compute_trends(db, user.id)


@router.get("/{trend_id}", response_model=TrendOut)
def get_trend(trend_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Trend:
    trend = db.get(Trend, trend_id)
    if trend is None or trend.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend not found")
    return trend


@router.get("/{trend_id}/videos", response_model=list[VideoOut])
def trend_videos(
    trend_id: int,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[VideoOut]:
    """The evidence behind a trend — the actual videos it was computed from."""
    trend = db.get(Trend, trend_id)
    if trend is None or trend.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trend not found")

    channel_ids = list(
        db.scalars(select(TrackedChannel.channel_id).where(TrackedChannel.user_id == user.id)).all()
    )
    rows = db.execute(
        select(Video, VideoIntelligence, Channel)
        .join(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.channel_id.in_(channel_ids))
        .where(VideoIntelligence.topic == trend.topic)
        .where(VideoIntelligence.subtopic == trend.subtopic)
        .order_by(VideoIntelligence.performance_ratio.desc())
        .limit(limit)
    ).all()
    return [_to_out(v, i, c) for v, i, c in rows]
