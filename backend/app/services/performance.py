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


def is_short(video: Video) -> bool:
    """Whether this is a Short, judged by duration.

    Duration is the only signal the API gives us. YouTube's own Shorts ceiling
    is 3 minutes, so that's the line. A duration of 0 means the field is
    missing rather than that the video is instantaneous — those are treated as
    long-form, which is both the commoner case and the safer error.
    """
    return 0 < (video.duration_seconds or 0) <= settings.shorts_max_seconds


def _median_of(videos: list[Video]) -> int:
    """Median views over mature videos, falling back to all of them."""
    if not videos:
        return 0
    cutoff = utcnow() - timedelta(days=BASELINE_MIN_AGE_DAYS)
    mature = [v.views for v in videos if v.published_at <= cutoff]
    if len(mature) >= BASELINE_MIN_SAMPLE:
        return compute_baseline(mature)
    # Not enough mature videos yet — fall back to everything rather than nothing.
    return compute_baseline([v.views for v in videos])


def channel_baselines(db: Session, channel: Channel) -> dict[str, int]:
    """Separate medians for Shorts and long-form, plus the pooled fallback.

    Pooling the two was quietly wrong for any channel that posts both, which
    in 2026 is most of them. Shorts routinely pull an order of magnitude more
    views than long-form on the same channel, so one median lands between the
    two clusters and describes neither: every ordinary long-form video reads
    as a severe underperformer and every ordinary Short reads as a near
    breakout. The trend engine then inherits both distortions through
    avg_performance and breakout_rate, skewing recommendations toward whatever
    topics happen to get covered in Shorts.

    A format bucket too thin to trust falls back to the pooled figure — which
    is exactly the old behaviour, and is correct for channels that only post
    one format, where the bucket and the pool are the same videos anyway.
    """
    videos = list(db.scalars(select(Video).where(Video.channel_id == channel.id)).all())
    pooled = _median_of(videos)

    shorts = [v for v in videos if is_short(v)]
    longform = [v for v in videos if not is_short(v)]

    return {
        "short": _median_of(shorts) if len(shorts) >= BASELINE_MIN_SAMPLE else pooled,
        "long": _median_of(longform) if len(longform) >= BASELINE_MIN_SAMPLE else pooled,
        "pooled": pooled,
    }


def channel_baseline(db: Session, channel: Channel) -> int:
    """The channel's overall median, ignoring format.

    Retained for callers that want one number for a channel — the competitor
    list, and the projection of a topic onto the user's own channel. Scoring
    an individual video must use `channel_baselines` instead.
    """
    return _median_of(list(db.scalars(select(Video).where(Video.channel_id == channel.id)).all()))


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
    """Recompute performance for every video on one channel.

    Each video is measured against the baseline for *its own format*, so a
    Short is compared with Shorts and a long-form video with long-form.
    """
    baselines = channel_baselines(db, channel)
    videos = db.scalars(select(Video).where(Video.channel_id == channel.id)).all()

    breakouts = 0
    for video in videos:
        baseline = baselines["short"] if is_short(video) else baselines["long"]
        ratio = performance_ratio(video.views, baseline)
        intel = _intelligence_for(db, video)
        # Storing the baseline actually used keeps the audit trail honest:
        # "3.2x their usual 40k" now names the right 40k.
        intel.baseline_views = baseline
        intel.performance_ratio = ratio
        intel.performance_score = performance_score(ratio)
        intel.is_breakout = is_breakout(ratio, threshold)
        intel.updated_at = utcnow()
        if intel.is_breakout:
            breakouts += 1

    db.commit()
    return {
        "channel_id": channel.id,
        "baseline": baselines["pooled"],
        "baseline_short": baselines["short"],
        "baseline_long": baselines["long"],
        "videos": len(videos),
        "breakouts": breakouts,
    }


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
