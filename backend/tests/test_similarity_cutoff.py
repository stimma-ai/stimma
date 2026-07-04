"""
Tests for the distribution-based relevance cutoff used by similarity_cutoff=auto.
"""

from utils.similarity import compute_relevance_cutoff


ABSOLUTE_FLOOR = 0.225


def test_spiky_distribution_cuts_above_the_body():
    """A clear head of high scores separated from a wide-spread body should raise the cutoff above the floor."""
    body = [0.15 + 0.0005 * i for i in range(200)]  # spans 0.15-0.2495
    head = [0.32, 0.318, 0.317, 0.315, 0.314]
    cutoff = compute_relevance_cutoff(body + head, absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff > ABSOLUTE_FLOOR
    kept = [s for s in body + head if s >= cutoff]
    assert set(kept) == set(head)


def test_flat_low_distribution_falls_back_to_floor():
    """A flat, low distribution (no real concept present) has no contrast to detect - stays at the floor."""
    scores = [0.19 + 0.0005 * (i % 20) for i in range(200)]
    cutoff = compute_relevance_cutoff(scores, absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff == ABSOLUTE_FLOOR
    assert all(s < cutoff for s in scores)


def test_flat_high_distribution_keeps_the_floor_not_drop_everything():
    """A homogeneous but relevant library (e.g. all-dogs queried with 'dog') must not be dropped
    just because it lacks contrast against its own body."""
    scores = [0.32] * 200
    cutoff = compute_relevance_cutoff(scores, absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff == ABSOLUTE_FLOOR
    assert all(s >= cutoff for s in scores)


def test_tiny_library_falls_back_to_flat_threshold():
    """Below the minimum sample size, there isn't enough data for a distribution shape - use the floor."""
    scores = [0.29, 0.10, 0.15, 0.28, 0.05]
    cutoff = compute_relevance_cutoff(scores, absolute_floor=ABSOLUTE_FLOOR, min_n=30)
    assert cutoff == ABSOLUTE_FLOOR


def test_identical_scores_is_degenerate_and_falls_back_to_floor():
    """Zero MAD (every score identical) must not divide by zero or blow up the cutoff."""
    scores = [0.24] * 50
    cutoff = compute_relevance_cutoff(scores, absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff == ABSOLUTE_FLOOR


def test_empty_scores_falls_back_to_floor():
    cutoff = compute_relevance_cutoff([], absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff == ABSOLUTE_FLOOR


def test_cutoff_never_drops_below_the_absolute_floor():
    """Even when the contrast test computes a lower value than the floor, the floor wins."""
    scores = [0.05 + 0.001 * (i % 5) for i in range(200)]
    cutoff = compute_relevance_cutoff(scores, absolute_floor=ABSOLUTE_FLOOR)
    assert cutoff >= ABSOLUTE_FLOOR
