from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import Channel, TrackedChannel, User, Video, VideoIntelligence
from app.schemas import VideoIntelligenceOut, VideoOut

router = APIRouter(tags=["videos"])


def _tracked_ids(db: Session, user_id: int) -> list[int]:
    return list(db.scalars(select(TrackedChannel.channel_id).where(TrackedChannel.user_id == user_id)).all())


def _to_out(video: Video, intel: VideoIntelligence | None, channel: Channel) -> VideoOut:
    return VideoOut(
        id=video.id,
        youtube_video_id=video.youtube_video_id,
        channel_id=video.channel_id,
        channel_name=channel.name,
        title=video.title,
        published_at=video.published_at,
        views=video.views,
        likes=video.likes,
        comments=video.comments,
        duration_seconds=video.duration_seconds,
        thumbnail_url=video.thumbnail_url,
        url=video.url,
        intelligence=VideoIntelligenceOut.model_validate(intel) if intel else None,
    )


@router.get("/channels/{channel_id}/videos", response_model=list[VideoOut])
def channel_videos(
    channel_id: int,
    limit: int = Query(30, le=200),
    sort: str = Query("recent", pattern="^(recent|performance|views)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[VideoOut]:
    if channel_id not in _tracked_ids(db, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not tracking that channel")

    order = {
        "recent": Video.published_at.desc(),
        "views": Video.views.desc(),
        "performance": VideoIntelligence.performance_ratio.desc(),
    }[sort]

    rows = db.execute(
        select(Video, VideoIntelligence, Channel)
        .outerjoin(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.channel_id == channel_id)
        .order_by(order)
        .limit(limit)
    ).all()
    return [_to_out(v, i, c) for v, i, c in rows]


@router.get("/videos/breakouts", response_model=list[VideoOut])
def breakouts(
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[VideoOut]:
    """Videos performing unusually well relative to their own creator's baseline."""
    channel_ids = _tracked_ids(db, user.id)
    if not channel_ids:
        return []

    rows = db.execute(
        select(Video, VideoIntelligence, Channel)
        .join(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.channel_id.in_(channel_ids))
        .where(VideoIntelligence.is_breakout.is_(True))
        .order_by(VideoIntelligence.performance_ratio.desc())
        .limit(limit)
    ).all()
    return [_to_out(v, i, c) for v, i, c in rows]
