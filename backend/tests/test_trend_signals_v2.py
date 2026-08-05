"""Tier-2 signals: recency, saturation, format breakdown, coverage gaps.

These are the signals meant to separate this from a generic "what's trending"
tool, so each one is pinned to the behaviour that makes it worth having.
"""
from __future__ import annotations

from app.services.briefing import own_channel_topics
from app.services.trends import (
    WEIGHTS,
    _format_performance,
    recency_share,
    saturation_for,
    score_components,
)


# --- Weights -------------------------------------------------------------


def test_weights_still_sum_to_one():
    """Adding a sixth signal must not quietly inflate every score."""
    assert round(sum(WEIGHTS.values()), 6) == 1.0


def test_performance_remains_the_heaviest_signal():
    """Rebalancing for recency must not demote the thing that matters most."""
    assert max(WEIGHTS, key=WEIGHTS.get) == "performance"


# --- Recency -------------------------------------------------------------


def test_recency_distinguishes_accelerating_from_fading():
    """The core fix: a topic that spiked days ago should not look like one
    happening right now."""
    window = 7
    accelerating = recency_share([0.5, 1.0, 2.0], window)  # all in the newer half
    fading = recency_share([5.0, 6.0, 6.5], window)  # all in the older half

    assert accelerating == 1.0
    assert fading == 0.0
    assert accelerating > fading


def test_evenly_spread_topic_is_neutral():
    assert recency_share([1.0, 2.0, 5.0, 6.0], 7) == 0.5


def test_recency_handles_no_videos():
    assert recency_share([], 7) == 0.0
    assert recency_share([1.0], 0) == 0.0


def test_fading_topic_scores_below_an_identical_fresh_one():
    """Same everything except when it happened."""
    common = dict(avg_performance=2.0, volume_growth=0.5, creator_count=5, breakout_rate=0.2, velocity=1.0)
    fresh = score_components(**common, recency=1.0)[0]
    stale = score_components(**common, recency=0.0)[0]
    assert fresh > stale


# --- Saturation ----------------------------------------------------------


def test_crowded_and_flat_is_flagged_as_too_late():
    result = saturation_for(creator_count=8, volume_growth=-0.2)
    assert result["level"] == "crowded"
    assert "too late" in result["note"]


def test_crowded_but_still_growing_is_only_filling():
    assert saturation_for(creator_count=8, volume_growth=0.1)["level"] == "filling"


def test_a_fast_growing_crowded_topic_is_still_open():
    """Lots of creators is fine while it's genuinely accelerating."""
    assert saturation_for(creator_count=9, volume_growth=0.9)["level"] == "open"


def test_few_creators_is_never_crowded():
    assert saturation_for(creator_count=2, volume_growth=-0.5)["level"] == "open"


# --- Format breakdown ----------------------------------------------------


def _record(fmt: str, ratio: float) -> dict:
    class _Intel:
        format = fmt

    return {"intel": _Intel(), "ratio": ratio}


def test_formats_are_ranked_by_performance_not_frequency():
    """top_format was a popularity contest; this answers what actually worked."""
    records = [
        _record("Tutorial", 0.6),
        _record("Tutorial", 0.8),
        _record("Tutorial", 0.7),
        _record("Experiment", 2.4),
        _record("Experiment", 2.6),
    ]
    rows = _format_performance(records)

    assert rows[0]["format"] == "Experiment", "best performing must lead, despite being rarer"
    assert rows[0]["avg_performance"] > rows[1]["avg_performance"]


def test_single_video_formats_are_dropped():
    """One video is an anecdote — showing it as an average implies otherwise."""
    rows = _format_performance([_record("Review", 9.9), _record("Tutorial", 1.0), _record("Tutorial", 1.2)])
    assert [r["format"] for r in rows] == ["Tutorial"]


def test_formats_ignore_unscored_and_unlabelled_videos():
    rows = _format_performance([_record(None, 2.0), _record(None, 2.0), _record("Review", 0.0), _record("Review", 0.0)])
    assert rows == []


# --- Coverage gaps -------------------------------------------------------


def test_gap_detection_is_case_insensitive(client, auth, db):
    """A user who posts "AI Agents" must not be told they've never covered it."""
    from app.models import Channel, TrackedChannel, Video, VideoIntelligence
    from app.utils.time import utcnow

    channel = Channel(
        youtube_channel_id="UCown", name="Mine", handle="mine", url="https://x", subscriber_count=1
    )
    db.add(channel)
    db.flush()
    db.add(TrackedChannel(user_id=1, channel_id=channel.id, type="own"))
    video = Video(
        youtube_video_id="v1",
        channel_id=channel.id,
        title="t",
        published_at=utcnow(),
        views=10,
        url="https://y",
    )
    db.add(video)
    db.flush()
    db.add(VideoIntelligence(video_id=video.id, topic="AI", subtopic="AI Agents"))
    db.commit()

    covered = own_channel_topics(db, 1)
    assert "ai agents" in covered


def test_no_own_channel_means_no_covered_topics(db):
    assert own_channel_topics(db, 999) == set()
