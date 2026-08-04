from __future__ import annotations

import statistics
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import current_user
from app.db import SessionLocal, get_db
from app.models import Channel, TrackedChannel, User, Video, VideoIntelligence
from app.schemas import ChannelOut, OnboardingRequest, TrackChannelRequest, TrackedChannelOut
from app.services import ingestion, pipeline
from app.services.youtube import ChannelNotFound, ProviderError, get_provider
from app.utils.logging import record_event
from app.utils.time import utcnow

router = APIRouter(prefix="/channels", tags=["channels"])


def _roll_up(db: Session, channel: Channel) -> dict:
    """Derived stats so the competitor list answers 'so what?' without a second call."""
    cutoff = utcnow() - timedelta(days=30)
    rows = db.execute(
        select(Video, VideoIntelligence)
        .outerjoin(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .where(Video.channel_id == channel.id)
    ).all()

    if not rows:
        return {"median_views": 0, "videos_last_30d": 0, "breakouts_last_30d": 0,
                "upload_cadence_days": None, "top_topics": []}

    recent = [(v, i) for v, i in rows if v.published_at >= cutoff]
    views = [v.views for v, _ in rows if v.views > 0]
    dates = sorted((v.published_at for v, _ in rows), reverse=True)[:12]
    gaps = [(dates[i] - dates[i + 1]).total_seconds() / 86400 for i in range(len(dates) - 1)]
    topics = Counter(i.subtopic for _, i in recent if i and i.subtopic)

    return {
        "median_views": int(statistics.median(views)) if views else 0,
        "videos_last_30d": len(recent),
        "breakouts_last_30d": sum(1 for _, i in recent if i and i.is_breakout),
        "upload_cadence_days": round(statistics.median(gaps), 1) if gaps else None,
        "top_topics": [t for t, _ in topics.most_common(3)],
    }


def _to_tracked_out(db: Session, tracked: TrackedChannel) -> TrackedChannelOut:
    channel = tracked.channel
    return TrackedChannelOut(
        **ChannelOut.model_validate(channel).model_dump(),
        tracked_id=tracked.id,
        type=tracked.type,
        **_roll_up(db, channel),
    )


def _ingest_and_analyse(user_id: int, channel_id: int) -> None:
    """Background: pull this channel's videos, then refresh the user's intelligence."""
    db = SessionLocal()
    try:
        channel = db.get(Channel, channel_id)
        if channel is None:
            return
        ingestion.ingest_channel(db, channel)
        pipeline.run_pipeline(db, user_id, skip_ingestion=True)
    except Exception as exc:
        record_event(db, "background.failure", f"ingest channel {channel_id}: {exc}", level="error")
    finally:
        db.close()


@router.post("/track", response_model=TrackedChannelOut, status_code=status.HTTP_201_CREATED)
def track_channel(
    payload: TrackChannelRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TrackedChannelOut:
    if payload.type == "competitor":
        existing = db.scalars(
            select(TrackedChannel).where(
                TrackedChannel.user_id == user.id, TrackedChannel.type == "competitor"
            )
        ).all()
        if len(existing) >= settings.max_competitors:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"MVP tracks up to {settings.max_competitors} competitors. Remove one first.",
            )

    try:
        channel = ingestion.resolve_and_store_channel(db, payload.url)
    except ChannelNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    tracked = db.scalar(
        select(TrackedChannel).where(
            TrackedChannel.user_id == user.id, TrackedChannel.channel_id == channel.id
        )
    )
    if tracked is None:
        tracked = TrackedChannel(user_id=user.id, channel_id=channel.id, type=payload.type)
        db.add(tracked)
    else:
        tracked.type = payload.type
    db.commit()
    db.refresh(tracked)

    background.add_task(_ingest_and_analyse, user.id, channel.id)
    return _to_tracked_out(db, tracked)


@router.post("/onboarding", response_model=list[TrackedChannelOut], status_code=status.HTTP_201_CREATED)
def onboarding(
    payload: OnboardingRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[TrackedChannelOut]:
    """Section 6 — three inputs, one call: own channel, competitors, niche."""
    if payload.niche:
        user.niche = payload.niche

    provider = get_provider()
    requests = [(payload.own_channel, "own")] + [
        (url, "competitor") for url in payload.competitors[: settings.max_competitors]
    ]

    tracked_rows: list[TrackedChannel] = []
    failures: list[str] = []
    for url, kind in requests:
        if not url or not url.strip():
            continue
        try:
            channel = ingestion.resolve_and_store_channel(db, url, provider)
        except (ChannelNotFound, ProviderError) as exc:
            failures.append(f"{url}: {exc}")
            continue

        tracked = db.scalar(
            select(TrackedChannel).where(
                TrackedChannel.user_id == user.id, TrackedChannel.channel_id == channel.id
            )
        )
        if tracked is None:
            tracked = TrackedChannel(user_id=user.id, channel_id=channel.id, type=kind)
            db.add(tracked)
        tracked_rows.append(tracked)

    db.commit()

    # The free tier allows 10,000 units/day and a channel search costs 100, so
    # a busy onboarding day can exhaust it. Recorded per onboarding rather than
    # summed at the end of the day, because the useful question when signups
    # start failing with a 403 is "which shape of URL is burning the budget",
    # and that is only answerable if the spend is attributed as it happens.
    units = getattr(provider, "units_used", 0)
    if units:
        record_event(
            db,
            "youtube.quota",
            f"resolved {len(tracked_rows)} channels for {units} units",
            user_id=user.id,
            units=units,
            channels=len(tracked_rows),
        )

    if not tracked_rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No channels could be resolved. {'; '.join(failures)}")

    for row in tracked_rows:
        db.refresh(row)

    background.add_task(_run_pipeline_bg, user.id)
    if failures:
        record_event(db, "onboarding.partial", "; ".join(failures), level="error", user_id=user.id)
    return [_to_tracked_out(db, row) for row in tracked_rows]


def _run_pipeline_bg(user_id: int) -> None:
    db = SessionLocal()
    try:
        pipeline.run_pipeline(db, user_id)
    except Exception as exc:
        record_event(db, "background.failure", f"pipeline for user {user_id}: {exc}", level="error")
    finally:
        db.close()


@router.get("/tracked", response_model=list[TrackedChannelOut])
def list_tracked(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[TrackedChannelOut]:
    rows = db.scalars(
        select(TrackedChannel).where(TrackedChannel.user_id == user.id).order_by(TrackedChannel.type, TrackedChannel.id)
    ).all()
    return [_to_tracked_out(db, row) for row in rows]


@router.get("/{channel_id}", response_model=TrackedChannelOut)
def get_channel(
    channel_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> TrackedChannelOut:
    tracked = db.scalar(
        select(TrackedChannel).where(
            TrackedChannel.user_id == user.id, TrackedChannel.channel_id == channel_id
        )
    )
    if tracked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not tracking that channel")
    return _to_tracked_out(db, tracked)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def untrack(channel_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    tracked = db.scalar(
        select(TrackedChannel).where(
            TrackedChannel.user_id == user.id, TrackedChannel.channel_id == channel_id
        )
    )
    if tracked is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not tracking that channel")
    db.delete(tracked)
    db.commit()
