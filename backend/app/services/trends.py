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
    "performance": 0.28,  # is the topic actually outperforming?
    "volume_growth": 0.22,  # is it accelerating vs the prior window?
    "creator_adoption": 0.18,  # is it broad, or one creator's hobby horse?
    "breakout_rate": 0.14,  # is it producing outliers?
    "recency": 0.10,  # is the activity now, or already over?
    "velocity": 0.08,  # raw publishing rate
}

# The value of a raw signal at which its normalised contribution saturates at 1.0.
SATURATION = {
    "performance": 3.0,  # 3× creator baseline
    "volume_growth": 1.0,  # +100% vs prior window
    "creator_adoption": 8.0,  # 8 distinct creators
    "breakout_rate": 0.4,  # 40% of videos are breakouts
    "recency": 1.0,  # already a 0–1 share; see recency_share()
    "velocity": 2.0,  # 2 videos/day
}


def recency_share(ages_in_days: list[float], window_days: int) -> float:
    """What share of the window's activity happened in its *newer* half.

    Every video in the window counted equally before this, so a topic that
    spiked six days ago and has since gone silent scored identically to one
    accelerating this morning — while the product's entire claim is that
    "rising" means rising. 0.5 is an evenly spread topic, above that is
    accelerating, below it is fading.

    Deliberately a share rather than an exponential decay: it survives being
    explained in one sentence in the score breakdown, which matters more here
    than a smoother curve.
    """
    if not ages_in_days or window_days <= 0:
        return 0.0
    midpoint = window_days / 2
    newer = sum(1 for age in ages_in_days if age <= midpoint)
    return newer / len(ages_in_days)


def saturation_for(creator_count: int, volume_growth: float) -> dict:
    """Whether a topic still has room, or everyone already got there.

    The signal nobody ships. Every tool in this category reports what is
    rising; none warn that a topic is crowded and cooling, which is exactly
    when acting on it costs the most and returns the least.
    """
    crowded = creator_count >= 5
    if crowded and volume_growth <= 0:
        return {
            "level": "crowded",
            "note": (
                f"{creator_count} creators are already on this and volume is no longer growing "
                "— likely too late to be early."
            ),
        }
    if crowded and volume_growth < 0.25:
        return {
            "level": "filling",
            "note": f"{creator_count} creators are covering this and growth is slowing.",
        }
    return {"level": "open", "note": ""}


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
    recency: float = 0.5,
) -> tuple[int, dict]:
    """Combine the signals into a 0–100 score plus a full audit trail.

    `recency` defaults to 0.5 — an evenly spread topic — so a caller that
    doesn't supply it is treated as neutral rather than as one that died.
    """
    raw = {
        "performance": avg_performance,
        "volume_growth": volume_growth,
        "creator_adoption": float(creator_count),
        "breakout_rate": breakout_rate,
        "recency": recency,
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


def _format_performance(records: list[dict], min_sample: int = 2) -> list[dict]:
    """How each format performed *within* this topic, best first.

    `top_format` only ever said which format was most common, which is a
    popularity contest — the useful question is which one worked. Formats
    below `min_sample` are dropped rather than reported: one video is an
    anecdote, and presenting it beside a real average would imply otherwise.
    """
    by_format: dict[str, list[float]] = {}
    for record in records:
        name = record["intel"].format
        ratio = record["ratio"]
        if not name or ratio <= 0:
            continue
        by_format.setdefault(name, []).append(ratio)

    rows = [
        {
            "format": name,
            "video_count": len(ratios),
            "avg_performance": round(statistics.mean(ratios), 3),
        }
        for name, ratios in by_format.items()
        if len(ratios) >= min_sample
    ]
    rows.sort(key=lambda row: row["avg_performance"], reverse=True)
    return rows


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

        # A video whose channel has no usable baseline yet scores 0.0, which
        # means "unknown", not "flopped". Those are excluded from the average
        # — and must be excluded from the breakout rate too, or the two
        # signals describe different populations: performance measured on the
        # scored videos, breakout rate diluted by the unscored ones. That
        # silently under-reports breakouts on newly-added channels, exactly
        # when a user is first forming an opinion of the product.
        scored = [r for r in window.recent_videos if r["ratio"] > 0]
        ratios = [r["ratio"] for r in scored]
        avg_performance = round(statistics.mean(ratios), 3) if ratios else 0.0

        # +100% when the topic appeared from nothing; symmetric otherwise.
        volume_growth = (
            round((recent_count - prior_count) / prior_count, 3) if prior_count else 1.0
        )
        creator_count = len({r["channel"].id for r in window.recent_videos})
        breakouts = sum(1 for r in scored if r["intel"].is_breakout)
        breakout_rate = breakouts / len(scored) if scored else 0.0
        velocity = round(recent_count / window_days, 3)

        ages = [
            max(0.0, (now - r["video"].published_at).total_seconds() / 86400)
            for r in window.recent_videos
        ]
        recency = round(recency_share(ages, window_days), 3)

        score, breakdown = score_components(
            avg_performance=avg_performance,
            volume_growth=volume_growth,
            creator_count=creator_count,
            breakout_rate=breakout_rate,
            velocity=velocity,
            recency=recency,
        )

        formats = [r["intel"].format for r in window.recent_videos if r["intel"].format]
        top_format = statistics.mode(formats) if formats else None
        format_breakdown = _format_performance(window.recent_videos)

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
                # "Everyone is already here and it's cooling" — the warning
                # that stops a recommendation being acted on too late.
                "saturation": saturation_for(creator_count, volume_growth),
                # Which format is actually working, not just which is most
                # common: the same topic can be a hit as an experiment and a
                # dud as a tutorial.
                "formats": format_breakdown,
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
