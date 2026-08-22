from math import exp

from sportsedge.mlb.prop_monte_carlo import (
    DEFAULT_SIMULATIONS, MIN_SIMULATIONS,
    simulate_count_line, simulate_hitter_one_plus_hit, simulate_nrfi,
)


def test_count_sim_is_deterministic_and_sums_to_one():
    a = simulate_count_line(mean=5.2, line=4.5, market="PITCHER_K", seed=7)
    b = simulate_count_line(mean=5.2, line=4.5, market="PITCHER_K", seed=7)
    assert a == b
    assert a.simulations == DEFAULT_SIMULATIONS == 50_000
    assert abs(a.over_prob + a.under_prob + a.push_prob - 1.0) < 1e-12
    assert a.push_prob == 0
    assert a.promotion_evidence is False


def test_integer_line_has_push_mass():
    r = simulate_count_line(mean=5.0, line=5.0, market="PITCHER_K", seed=11)
    assert r.push_prob > 0


def test_hitter_hit_prob_rises_with_projected_pa():
    low = simulate_hitter_one_plus_hit(per_pa_hit_prob=.24, projected_pa=3.0, seed=3)
    high = simulate_hitter_one_plus_hit(per_pa_hit_prob=.24, projected_pa=4.5, seed=3)
    assert high > low


def test_nrfi_matches_poisson_zero_run_baseline_when_no_mean_uncertainty():
    away, home = .28, .31
    sim = simulate_nrfi(away_first_inning_run_mean=away, home_first_inning_run_mean=home,
                        mean_cv=0, simulations=50_000, seed=17)
    expected = exp(-(away + home))
    assert abs(sim - expected) < .015


def test_low_sim_count_fails_closed():
    try:
        simulate_count_line(mean=4.0, line=3.5, market="PITCHER_K", simulations=MIN_SIMULATIONS - 1)
    except ValueError as exc:
        assert str(MIN_SIMULATIONS) in str(exc)
    else:
        raise AssertionError("undersized simulation must fail")
