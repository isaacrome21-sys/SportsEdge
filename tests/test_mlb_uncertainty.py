import random

from sportsedge.mlb_uncertainty import (
    beta_posterior,
    expected_value_decimal,
    sample_beta,
    sample_truncated_normal,
    summarize_draws,
    uncertainty_haircut,
)


def test_beta_posterior_shrinks_small_sample():
    p = beta_posterior(successes=8, trials=10, prior_mean=.25, prior_strength=100)
    assert .25 < p.mean < .35


def test_beta_sampling_reproducible_with_seed():
    p = beta_posterior(successes=30, trials=100, prior_mean=.25, prior_strength=50)
    assert sample_beta(p, random.Random(7)) == sample_beta(p, random.Random(7))


def test_truncated_normal_respects_bounds():
    rng = random.Random(4)
    xs = [sample_truncated_normal(mean=90, sd=15, low=50, high=120, rng=rng) for _ in range(1000)]
    assert min(xs) >= 50
    assert max(xs) <= 120


def test_summary_reports_distribution_and_over_probability():
    s = summarize_draws([1, 2, 3, 4, 5], over_line=3.5)
    assert s.mean == 3
    assert s.q50 == 3
    assert s.probability_over == .4


def test_ev_decimal():
    assert round(expected_value_decimal(win_probability=.55, decimal_odds=2.0), 6) == .1


def test_uncertainty_haircut_cannot_create_edge():
    assert uncertainty_haircut(raw_edge=.04, probability_sd=.03) == .01
    assert uncertainty_haircut(raw_edge=-.02, probability_sd=.03) == -.02
