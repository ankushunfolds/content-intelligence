from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.db import get_db
from app.models import Channel, TrackedChannel, User, Video, VideoIntelligence
from app.schemas import RefreshResponse
from app.services import briefing, pipeline
from app.services.trends import top_trends
from app.utils.format import compact_number, multiplier, percent
from app.utils.time import utcnow

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/today")
def today(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Everything the dashboard needs in one call (Section 7)."""
    brief = briefing.generate_brief(db, user.id)
    content = brief.content or {}

    channel_ids = list(
        db.scalars(select(TrackedChannel.channel_id).where(TrackedChannel.user_id == user.id)).all()
    )

    cutoff = utcnow() - timedelta(days=settings.trend_window_days)
    activity = []
    if channel_ids:
        rows = db.execute(
            select(Channel, Video, VideoIntelligence)
            .join(Video, Video.channel_id == Channel.id)
            .outerjoin(VideoIntelligence, VideoIntelligence.video_id == Video.id)
            .where(Channel.id.in_(channel_ids))
            .where(Video.published_at >= cutoff)
            .order_by(Video.published_at.desc())
            .limit(12)
        ).all()
        activity = [
            {
                "channel_id": channel.id,
                "channel_name": channel.name,
                "title": video.title,
                "url": video.url,
                "published_at": video.published_at.isoformat(),
                "views_display": compact_number(video.views),
                "performance": multiplier(intel.performance_ratio) if intel else "—",
                "is_breakout": bool(intel and intel.is_breakout),
                "subtopic": intel.subtopic if intel else None,
            }
            for channel, video, intel in rows
        ]

    return {
        "headline": content.get("headline"),
        "brief_date": brief.brief_date.isoformat(),
        "generated_by": brief.generated_by,
        "opportunities": content.get("opportunities", []),
        "breakouts": content.get("competitor_highlights", []),
        "rising_trends": content.get("rising_trends", []),
        "competitor_activity": activity,
        "stats": content.get("stats", {}),
        "data_mode": {
            "youtube": "live" if settings.using_real_youtube else "seed",
            "llm": settings.llm_provider if settings.using_real_llm else "mock",
        },
    }


@router.post("/refresh", response_model=RefreshResponse)
def refresh(db: Session = Depends(get_db), user: User = Depends(current_user)) -> RefreshResponse:
    """Run the whole pipeline now: ingest → score → classify → trends → brief."""
    return RefreshResponse(**pipeline.run_pipeline(db, user.id))
