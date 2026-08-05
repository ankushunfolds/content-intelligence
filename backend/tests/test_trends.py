"""The trend score must be deterministic and inspectable (Section 11)."""
from __future__ import annotations

from app.services.trends import WEIGHTS, normalise, score_components


def _score(**kwargs) -> int:
    base = {
        "avg_performance": 1.0,
        "volume_growth": 0.0,
        "creator_count": 1,
        "breakout_rate": 0.0,
        "velocity": 0.1,
    }
    return score_components(**{**base, **kwargs})[0]


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_average_performance_contributes_nothing():
    """1× is by definition ordinary; it should not earn score."""
    assert normalise("performance", 1.0) == 0.0


def test_normalisation_is_clamped():
    assert normalise("performance", 100.0) == 1.0
    assert normalise("volume_growth", -5.0) == 0.0
    assert normalise("creator_adoption", 500) == 1.0


def test_score_is_bounded():
    """Every signal at its floor scores 0; every signal maxed scores 100.

    `recency` is passed explicitly here: its default is 0.5 (neutral, for
    callers with no age data), so relying on the default would leave the
    "everything is dead" case scoring 5 rather than 0.
    """
    low = score_components(
        avg_performance=0.0,
        volume_growth=-1.0,
        creator_count=0,
        breakout_rate=0.0,
        velocity=0.0,
        recency=0.0,
    )[0]
    high = score_components(
        avg_performance=10.0,
        volume_growth=5.0,
        creator_count=50,
        breakout_rate=1.0,
        velocity=10.0,
        recency=1.0,
    )[0]
    assert low == 0
    assert high == 100


def test_unsupplied_recency_is_neutral_not_zero():
    """A caller without age data must not be penalised as though the topic died."""
    neutral = score_components(
        avg_performance=2.0, volume_growth=0.5, creator_count=4, breakout_rate=0.2, velocity=1.0
    )[0]
    explicit = score_components(
        avg_performance=2.0,
        volume_growth=0.5,
        creator_count=4,
        breakout_rate=0.2,
        velocity=1.0,
        recency=0.5,
    )[0]
    assert neutral == explicit


def test_score_is_deterministic():
    args = dict(avg_performance=2.7, volume_growth=0.43, creator_count=7, breakout_rate=0.2, velocity=0.9)
    assert score_components(**args)[0] == score_components(**args)[0]


def test_performance_moves_the_score_more_than_volume():
    """'Many people talked about AI' must lose to 'AI is outperforming'."""
    volume_only = _score(volume_growth=1.0)
    performance_only = _score(avg_performance=3.0)
    assert performance_only > volume_only


def test_broad_adoption_beats_a_single_creator():
    assert _score(creator_count=8) > _score(creator_count=1)


def test_breakdown_explains_the_whole_score():
    score, breakdown = score_components(
        avg_performance=2.7, volume_growth=0.43, creator_count=7, breakout_rate=0.25, velocity=0.8
    )
    assert set(breakdown) == set(WEIGHTS)
    contributions = sum(part["contribution"] for part in breakdown.values())
    assert abs(contributions - score) <= 1  # rounding only
    for part in breakdown.values():
        assert {"raw", "normalised", "weight", "contribution"} <= set(part)
