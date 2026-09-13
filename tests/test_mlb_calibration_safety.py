from sportsedge.mlb_calibration_safety import edge_monotonicity_check, shrink_probability


def test_shrinkage_is_strong_with_small_sample():
    r = shrink_probability(raw_probability=.70, reference_probability=.50, sample_n=20, half_reliability_n=200)
    assert .50 < r.shrunk_probability < .55


def test_shrinkage_relaxes_with_large_sample():
    r = shrink_probability(raw_probability=.70, reference_probability=.50, sample_n=2000, half_reliability_n=200)
    assert r.shrunk_probability > .67


def test_monotonicity_quarantines_inverted_signal():
    probs = [.20] * 60 + [.80] * 60
    outcomes = [1] * 40 + [0] * 20 + [1] * 20 + [0] * 40
    r = edge_monotonicity_check(probs, outcomes, minimum_n=100)
    assert r.action == "QUARANTINE_RESEARCH"


def test_monotonicity_passes_ordered_signal():
    probs = [.20] * 60 + [.80] * 60
    outcomes = [1] * 20 + [0] * 40 + [1] * 40 + [0] * 20
    r = edge_monotonicity_check(probs, outcomes, minimum_n=100)
    assert r.action == "PASS"


def test_monotonicity_requires_sample():
    r = edge_monotonicity_check([.2, .8], [0, 1], minimum_n=100)
    assert r.action == "INSUFFICIENT_EVIDENCE"
