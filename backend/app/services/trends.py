"""Phase 5 — the trend engine (Section 11).

A trend is not "people talked about AI". It is "AI-agent videos are appearing
more often AND outperforming their creators' normal content".

The score is deterministic arithmetic over database rows. Every component is
stored alongside it so the number can be taken apart and argued with. No part of
this file calls an LLM.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, TrackedChannel, Trend, Video, VideoIntelligence
from app.utils.logging import record_event
from app.utils.time import utcnow

# Each weight says: how much does this signal matter in deciding "is this worth
# the creator's attention?". They sum to 1.0.
WEIGHTS = {
    "performance": 0.30,  # is the topic actually outperforming?
    "volume_growth": 0.25,  # is it accelerating vs the prior window?
    "creator_adoption": 0.20,  # is it broad, or one creator's hobby horse?
    "breakout_rate": 0.15,  # is it producing outliers?
    "velocity": 0.10,  # raw publishing rate
}

# The value of a raw signal at which its normalised contribution saturates at 1.0.
SATURATION = {
    "performance": 3.0,  # 3× creator baseline
    "volume_growth": 1.0,  # +100% vs prior window
    "creator_adoption": 8.0,  # 8 distinct creators
    "breakout_rate": 0.4,  # 40% of videos are breakouts
    "velocity": 2.0,  # 2 videos/day
}


@dataclass
class TopicWindow:
    topic: str
    subtopic: str
    recent_videos: list = field(default_factory=list)
    prior_videos: list = field(default_factory=list)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalise(signal: str, raw: float) -> float:
    """Map a raw signal onto 0–1 against its saturation point."""
    ceiling = SATURATION[signal]
    if signal == "performance":
        # 1× is average and should contribute nothing; 3× saturates.
        return _clamp01((raw - 1.0) / (ceiling - 1.0)) if ceiling > 1 else 0.0
    return _clamp01(raw / ceiling)


def score_components(
    *,
    avg_performance: float,
    volume_growth: float,
    creator_count: int,
    breakout_rate: float,
    velocity: float,
) -> tuple[int, dict]:
    """Combine the five signals into a 0–100 score plus a full audit trail."""
    raw = {
        "performance": avg_performance,
        "volume_growth": volume_growth,
        "creator_adoption": float(creator_count),
        "breakout_rate": breakout_rate,
        "velocity": velocity,
    }

    breakdown: dict[str, dict] = {}
    total = 0.0
    for signal, value in raw.items():
        normalised = normalise(signal, value)
        contribution = normalised * WEIGHTS[signal]
        total += contribution
        breakdown[signal] = {
            "raw": round(value, 3),
            "normalised": round(normalised, 3),
            "weight": WEIGHTS[signal],
            "contribution": round(contribution * 100, 1),
        }

    return int(round(total * 100)), breakdown


def _tracked_channel_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.scalars(select(TrackedChannel.channel_id).where(TrackedChannel.user_id == user_id)).all()
    )


def _collect_windows(db: Session, channel_ids: list[int], window_days: int, now: datetime) -> dict:
    """Bucket every classified video into the recent window or the one before it."""
    recent_start = now - timedelta(days=window_days)
    prior_start = now - timedelta(days=window_days * 2)

    rows = db.execute(
        select(Video, VideoIntelligence, Channel)
        .join(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.channel_id.in_(channel_ids))
        .where(Video.published_at >= prior_start)
        .where(VideoIntelligence.topic.is_not(None))
    ).all()

    windows: dict[tuple[str, str], TopicWindow] = {}
    for video, intel, channel in rows:
        key = (intel.topic, intel.subtopic or intel.topic)
        window = windows.setdefault(key, TopicWindow(topic=key[0], subtopic=key[1]))
        record = {
            "video": video,
            "intel": intel,
            "channel": channel,
            "ratio": intel.performance_ratio or 0.0,
        }
        if video.published_at >= recent_start:
            window.recent_videos.append(record)
        else:
            window.prior_videos.append(record)
    return windows


def compute_trends(db: Session, user_id: int, window_days: int | None = None) -> list[Trend]:
    """Recompute this user's trend table from scratch. Cheap and idempotent."""
    window_days = window_days or settings.trend_window_days
    now = utcnow()

    channel_ids = _tracked_channel_ids(db, user_id)

    # Wipe the previous run before the empty-channels early return, not after
    # it. Otherwise a user who untracks every channel keeps their last trend
    # snapshot forever — it has no channels to be recomputed from, so nothing
    # ever clears it, and it keeps surfacing in every future brief.
    for stale in db.scalars(select(Trend).where(Trend.user_id == user_id)).all():
        db.delete(stale)
    db.flush()

    if not channel_ids:
        db.commit()
        return []

    windows = _collect_windows(db, channel_ids, window_days, now)

    trends: list[Trend] = []
    for (topic, subtopic), window in windows.items():
        recent_count = len(window.recent_videos)
        if recent_count < settings.min_videos_for_trend:
            continue  # too thin to call a trend

        prior_count = len(window.prior_videos)
        ratios = [r["ratio"] for r in window.recent_videos if r["ratio"] > 0]
        avg_performance = round(statistics.mean(ratios), 3) if ratios else 0.0

        # +100% when the topic appeared from nothing; symmetric otherwise.
        volume_growth = (
            round((recent_count - prior_count) / prior_count, 3) if prior_count else 1.0
        )
        creator_count = len({r["channel"].id for r in window.recent_videos})
        breakouts = sum(1 for r in window.recent_videos if r["intel"].is_breakout)
        breakout_rate = breakouts / recent_count
        velocity = round(recent_count / window_days, 3)

        score, breakdown = score_components(
            avg_performance=avg_performance,
            volume_growth=volume_growth,
            creator_count=creator_count,
            breakout_rate=breakout_rate,
            velocity=velocity,
        )

        formats = [r["intel"].format for r in window.recent_videos if r["intel"].format]
        top_format = statistics.mode(formats) if formats else None

        trend = Trend(
            user_id=user_id,
            topic=topic,
            subtopic=subtopic,
            trend_score=score,
            volume_growth=volume_growth,
            video_velocity=velocity,
            avg_performance=avg_performance,
            creator_count=creator_count,
            video_count=recent_count,
            breakout_count=breakouts,
            top_format=top_format,
            components={
                "window_days": window_days,
                "recent_videos": recent_count,
                "prior_videos": prior_count,
                "weights": WEIGHTS,
                "signals": breakdown,
            },
            detected_at=now,
        )
        db.add(trend)
        trends.append(trend)

    db.commit()
    trends.sort(key=lambda t: t.trend_score, reverse=True)
    record_event(db, "trends.computed", f"{len(trends)} trends for user {user_id}", user_id=user_id, count=len(trends))
    return trends


def top_trends(db: Session, user_id: int, limit: int = 10) -> list[Trend]:
    return list(
        db.scalars(
            select(Trend)
            .where(Trend.user_id == user_id)
            .order_by(Trend.trend_score.desc())
            .limit(limit)
        ).all()
    )
