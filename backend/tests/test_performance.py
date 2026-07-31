"""The performance metric is the foundation of every other signal, so it gets
the most direct tests. All arithmetic, no mocking needed."""
from __future__ import annotations

from app.services.performance import (
    compute_baseline,
    is_breakout,
    performance_ratio,
    performance_score,
)


def test_baseline_is_median_not_mean():
    # One viral video must not drag the baseline up.
    views = [10_000, 11_000, 12_000, 13_000, 900_000]
    assert compute_baseline(views) == 12_000


def test_baseline_ignores_zero_view_videos():
    assert compute_baseline([0, 0, 100, 200, 300]) == 200


def test_baseline_of_nothing_is_zero():
    assert compute_baseline([]) == 0


def test_ratio_matches_the_spec_example():
    # Section 9: median 50,000, video 250,000 -> 5×
    assert performance_ratio(250_000, 50_000) == 5.0


def test_ratio_is_zero_when_no_baseline_exists():
    assert performance_ratio(1_000, 0) == 0.0


def test_small_creator_can_outrank_a_large_one():
    """The whole point of relative performance (Section 9)."""
    small = performance_ratio(200_000, 40_000)   # 50K subs, punching up
    large = performance_ratio(500_000, 800_000)  # 5M subs, underperforming
    assert small > large


def test_score_puts_average_performance_at_the_midpoint():
    assert performance_score(1.0) == 50


def test_score_is_monotonic_and_bounded():
    scores = [performance_score(r) for r in (0.2, 0.5, 1.0, 2.0, 5.0, 50.0)]
    assert scores == sorted(scores)
    assert scores[0] >= 0 and scores[-1] <= 100


def test_breakout_threshold_is_inclusive_and_configurable():
    assert is_breakout(3.0, threshold=3.0)
    assert not is_breakout(2.99, threshold=3.0)
    assert is_breakout(2.0, threshold=1.5)
