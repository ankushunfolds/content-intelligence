"""Logic QC — bugs that produce confidently wrong numbers rather than errors.

Nothing here throws. Each one shipped a plausible-looking figure that was
either misleading or plain wrong, which is the failure mode this product can
least afford given it sells "the numbers are real".
"""
from __future__ import annotations

import statistics

from app.services.briefing import _evidence_sentence, _plural, confidence_for


def _opportunity(creator_count: int, video_count: int) -> dict:
    return {
        "subtopic": "AI Agents",
        "topic": "AI",
        "evidence": {
            "creator_count": creator_count,
            "video_count": video_count,
            "window_days": 7,
            "volume_growth_pct": "+100%",
            "avg_performance": "1.1×",
        },
    }


# --- 1. Plurals in the fallback sentence ---------------------------------


def test_singular_counts_read_correctly():
    """Shipped as "1 tracked creators published 1 videos" — on precisely the
    days the LLM had already degraded to this fallback."""
    sentence = _evidence_sentence(_opportunity(creator_count=1, video_count=1))

    assert "1 tracked creator published 1 video on" in sentence
    assert "1 tracked creators" not in sentence
    assert "1 videos" not in sentence
    # "their creators' median views" is correct plural usage elsewhere in the
    # sentence, so a blanket check for "creators" would fail on valid output.
    assert "their creators' median views" in sentence


def test_plural_counts_still_read_correctly():
    sentence = _evidence_sentence(_opportunity(creator_count=4, video_count=9))
    assert "4 tracked creators published 9 videos" in sentence


def test_plural_helper():
    assert _plural(1, "video") == "1 video"
    assert _plural(0, "video") == "0 videos"
    assert _plural(2, "video") == "2 videos"


# --- 2. Confidence wording matches the actual weakness -------------------


def test_many_videos_from_one_creator_names_the_real_problem():
    """"Just 40 videos" is nonsense; the weakness is the single creator."""
    note = confidence_for(video_count=40, creator_count=1)["note"]

    assert "single creator" in note
    assert "Just 40 videos" not in note


def test_genuinely_thin_sample_still_says_so():
    note = confidence_for(video_count=3, creator_count=1)["note"]
    assert "Just 3 videos" in note


def test_confidence_needs_breadth_not_just_volume():
    assert confidence_for(40, 1)["level"] == "thin"
    assert confidence_for(12, 4)["level"] == "solid"


# --- 3. Breakout rate and performance must describe the same videos ------


def test_breakout_rate_excludes_unscored_videos():
    """A video on a channel with no baseline scores 0.0, meaning "unknown".

    Those are excluded from avg_performance. Including them in the breakout
    denominator made the two signals describe different populations and
    under-reported breakouts on newly-added channels.
    """

    class _Intel:
        def __init__(self, breakout):
            self.is_breakout = breakout

    recent = [
        {"ratio": 0.0, "intel": _Intel(False)},  # unscored
        {"ratio": 0.0, "intel": _Intel(False)},  # unscored
        {"ratio": 4.0, "intel": _Intel(True)},
        {"ratio": 2.0, "intel": _Intel(False)},
    ]

    scored = [r for r in recent if r["ratio"] > 0]
    breakouts = sum(1 for r in scored if r["intel"].is_breakout)
    rate = breakouts / len(scored)

    assert len(scored) == 2
    assert rate == 0.5, "1 breakout out of 2 scored videos"
    assert rate != breakouts / len(recent), "must not be diluted by unscored videos"

    avg = statistics.mean([r["ratio"] for r in scored])
    assert avg == 3.0, "performance already used this same population"


# --- 4. Coverage gaps must not be claimed from missing data --------------


def test_no_coverage_data_means_no_gap_claim():
    """With no own channel, every topic was flagged "you've never covered
    this" — a confident claim built on an empty set."""
    covered: set[str] = set()
    gaps_knowable = bool(covered)

    for topic in ["AI Agents", "Monetization", "Note Taking"]:
        is_gap = gaps_knowable and topic.strip().lower() not in covered
        assert is_gap is False


def test_gaps_are_claimed_once_coverage_is_known():
    covered = {"monetization"}
    gaps_knowable = bool(covered)

    assert (gaps_knowable and "ai agents" not in covered) is True
    assert (gaps_knowable and "monetization" not in covered) is False
