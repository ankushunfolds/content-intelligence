"""Shorts and long-form need separate baselines.

Pooling them was silently wrong for any channel posting both — which in 2026
is most of them. Shorts routinely pull an order of magnitude more views on the
same channel, so one median lands between the two clusters and describes
neither.

Nothing about the old behaviour looked broken: the numbers were plausible,
just wrong, and the trend engine inherited the distortion.
"""
from __future__ import annotations

from datetime import timedelta
from itertools import count

import pytest

from app.config import settings
from app.models import Channel, Video
from app.services.performance import (
    channel_baseline,
    channel_baselines,
    is_short,
    performance_ratio,
    score_channel,
)
from app.utils.time import utcnow


def _channel(db, name="Mixed") -> Channel:
    channel = Channel(
        youtube_channel_id=f"UC{name}",
        name=name,
        handle=name.lower(),
        url="https://youtube.com/x",
        subscriber_count=1000,
    )
    db.add(channel)
    db.flush()
    return channel


_ids = count()


def _video(db, channel, views: int, duration: int, age_days: int = 30) -> Video:
    # A monotonic counter, not id(object()) — CPython reuses addresses once the
    # temporary is collected, which produced duplicate video ids.
    video = Video(
        youtube_video_id=f"v{next(_ids)}",
        channel_id=channel.id,
        title="t",
        published_at=utcnow() - timedelta(days=age_days),
        views=views,
        duration_seconds=duration,
        url="https://youtube.com/watch",
    )
    db.add(video)
    return video


# --- Classification ------------------------------------------------------


def test_duration_decides_what_counts_as_a_short():
    class _V:
        def __init__(self, d):
            self.duration_seconds = d

    assert is_short(_V(30)) is True
    assert is_short(_V(settings.shorts_max_seconds)) is True
    assert is_short(_V(settings.shorts_max_seconds + 1)) is False
    assert is_short(_V(900)) is False


def test_missing_duration_is_treated_as_long_form():
    """0 means the field is absent, not that the video is instantaneous."""

    class _V:
        duration_seconds = 0

    assert is_short(_V()) is False


# --- The distortion this fixes -------------------------------------------


def test_mixed_channel_gets_separate_baselines(db):
    channel = _channel(db)
    for _ in range(10):
        _video(db, channel, views=100_000, duration=900)  # long-form
        _video(db, channel, views=1_000_000, duration=45)  # Shorts
    db.commit()

    baselines = channel_baselines(db, channel)

    assert baselines["long"] == 100_000
    assert baselines["short"] == 1_000_000
    assert baselines["long"] != baselines["pooled"], "pooling described neither cluster"


def test_ordinary_videos_score_near_1x_in_both_formats(db):
    """The heart of it: before this, a typical long-form video scored ~0.2x
    and a typical Short ~2x, on a channel where both were entirely normal."""
    channel = _channel(db)
    for _ in range(10):
        _video(db, channel, views=100_000, duration=900)
        _video(db, channel, views=1_000_000, duration=45)
    db.commit()

    score_channel(db, channel)

    longform = db.query(Video).filter(Video.duration_seconds == 900).first()
    short = db.query(Video).filter(Video.duration_seconds == 45).first()

    assert longform.intelligence.performance_ratio == pytest.approx(1.0, abs=0.05)
    assert short.intelligence.performance_ratio == pytest.approx(1.0, abs=0.05)
    assert longform.intelligence.is_breakout is False
    assert short.intelligence.is_breakout is False


def test_pooling_would_have_misjudged_both(db):
    """Guards the fix by demonstrating what the old maths produced."""
    channel = _channel(db)
    for _ in range(10):
        _video(db, channel, views=100_000, duration=900)
        _video(db, channel, views=1_000_000, duration=45)
    db.commit()

    pooled = channel_baselines(db, channel)["pooled"]

    assert performance_ratio(100_000, pooled) < 0.3, "long-form looked like a flop"
    assert performance_ratio(1_000_000, pooled) > 1.5, "Shorts looked like near-breakouts"


def test_a_genuine_short_breakout_is_still_detected(db):
    """Separating baselines must not blunt real signal."""
    channel = _channel(db)
    for _ in range(10):
        _video(db, channel, views=1_000_000, duration=45)
    _video(db, channel, views=5_000_000, duration=45, age_days=5)
    db.commit()

    score_channel(db, channel)

    viral = db.query(Video).filter(Video.views == 5_000_000).first()
    assert viral.intelligence.is_breakout is True


# --- Channels that post only one format ----------------------------------


def test_single_format_channel_is_unaffected(db):
    """The common case must behave exactly as before."""
    channel = _channel(db, "LongOnly")
    for views in [80_000, 90_000, 100_000, 110_000, 120_000, 100_000]:
        _video(db, channel, views=views, duration=900)
    db.commit()

    baselines = channel_baselines(db, channel)

    assert baselines["long"] == baselines["pooled"] == channel_baseline(db, channel)
    # No Shorts to measure, so that bucket falls back rather than reporting 0.
    assert baselines["short"] == baselines["pooled"]


def test_thin_format_bucket_falls_back_instead_of_reporting_zero(db):
    """Two Shorts is not a baseline. Falling back beats inventing one."""
    channel = _channel(db, "MostlyLong")
    for _ in range(10):
        _video(db, channel, views=100_000, duration=900)
    _video(db, channel, views=5_000, duration=30)
    _video(db, channel, views=6_000, duration=30)
    db.commit()

    baselines = channel_baselines(db, channel)

    assert baselines["short"] == baselines["pooled"]
    assert baselines["short"] > 0
