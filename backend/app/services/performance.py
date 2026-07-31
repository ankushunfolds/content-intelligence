"""Phase 4 — performance intelligence.

Pure Python, pure arithmetic, no LLM (Rule 4). Section 9 defines the metric:

    performance_ratio = video_views / creator_median_views

Relative-to-creator, so a 50K-subscriber channel doing 200K views outranks a
5M-subscriber channel doing 500K.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, Video, VideoIntelligence
from app.utils.logging import record_event
from app.utils.time import utcnow

# Videos younger than this are still accumulating views, so they'd drag the
# median down. They're excluded from the baseline but still get scored against it.
BASELINE_MIN_AGE_DAYS = 3
BASELINE_MIN_SAMPLE = 5


def compute_baseline(views: list[int]) -> int:
    """Median views for a creator. Median, not mean — one viral video shouldn't move it."""
    clean = [v for v in views if v > 0]
    if not clean:
        return 0
    return int(statistics.median(clean))


def channel_baseline(db: Session, channel: Channel) -> int:
    videos = db.scalars(select(Video).where(Video.channel_id == channel.id)).all()
    if not videos:
        return 0

    cutoff = utcnow() - timedelta(days=BASELINE_MIN_AGE_DAYS)
    mature = [v.views for v in videos if v.published_at <= cutoff]
    if len(mature) >= BASELINE_MIN_SAMPLE:
        return compute_baseline(mature)
    # Not enough mature videos yet — fall back to everything rather than nothing.
    return compute_baseline([v.views for v in videos])


def performance_ratio(views: int, baseline: int) -> float:
    if baseline <= 0:
        return 0.0
    return round(views / baseline, 3)


def performance_score(ratio: float) -> int:
    """Map an unbounded ratio onto 0–100 for display.

    1× (exactly average for the creator) lands at 50; 5× saturates near 100.
    Log-shaped because the difference between 1× and 2× matters more than 8× vs 9×.
    """
    if ratio <= 0:
        return 0
    import math

    score = 50 + 50 * (math.log(ratio) / math.log(5))
    return int(max(0, min(100, round(score))))


def is_breakout(ratio: float, threshold: float | None = None) -> bool:
    """Section 12. Threshold is configurable via BREAKOUT_THRESHOLD."""
    return ratio >= (threshold if threshold is not None else settings.breakout_threshold)


def _intelligence_for(db: Session, video: Video) -> VideoIntelligence:
    if video.intelligence is not None:
        return video.intelligence

    intel = VideoIntelligence(video_id=video.id)
    db.add(intel)
    try:
        db.flush()
    except IntegrityError:
        # Same trade-off noted in ingestion.upsert_channel: this rolls back
        # the whole session, which can also discard other videos already
        # scored earlier in this same `score_channel` loop. A SAVEPOINT would
        # scope it correctly but SQLite's dialect doesn't support real
        # savepoints without extra engine setup. Narrow window in practice —
        # two scoring runs landing on the same unscored video at the same
        # instant — and `score_channels` is safe to simply re-run if it does.
        db.rollback()
        existing = db.scalar(select(VideoIntelligence).where(VideoIntelligence.video_id == video.id))
        if existing is None:
            raise
        video.intelligence = existing
        return existing
    video.intelligence = intel
    return intel


def score_channel(db: Session, channel: Channel, threshold: float | None = None) -> dict:
    """Recompute performance for every video on one channel."""
    baseline = channel_baseline(db, channel)
    videos = db.scalars(select(Video).where(Video.channel_id == channel.id)).all()

    breakouts = 0
    for video in videos:
        ratio = performance_ratio(video.views, baseline)
        intel = _intelligence_for(db, video)
        intel.baseline_views = baseline
        intel.performance_ratio = ratio
        intel.performance_score = performance_score(ratio)
        intel.is_breakout = is_breakout(ratio, threshold)
        intel.updated_at = utcnow()
        if intel.is_breakout:
            breakouts += 1

    db.commit()
    return {"channel_id": channel.id, "baseline": baseline, "videos": len(videos), "breakouts": breakouts}


def score_channels(db: Session, channels: list[Channel], threshold: float | None = None) -> dict:
    total_videos = 0
    total_breakouts = 0
    for channel in channels:
        result = score_channel(db, channel, threshold)
        total_videos += result["videos"]
        total_breakouts += result["breakouts"]

    record_event(
        db,
        "performance.scored",
        f"{total_videos} videos across {len(channels)} channels, {total_breakouts} breakouts",
        videos=total_videos,
        breakouts=total_breakouts,
    )
    return {"videos_scored": total_videos, "breakouts": total_breakouts}
