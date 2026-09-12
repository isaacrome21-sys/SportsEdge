from sportsedge.mlb.environment_effects import EnvironmentEffects, from_percent_adjustments
from sportsedge.mlb.prop_distributions import (
    hitter_hit_probability, hits_allowed_mean, poisson_line,
    recorded_outs_mean, strikeout_mean, total_bases_mean,
)


def test_environment_channels_are_independent():
    e = from_percent_adjustments(hr_pct=20, xbh_pct=-10, runs_pct=5, k_pct=-3)
    assert e.hr == 1.20
    assert e.xbh == 0.90
    assert e.runs == 1.05
    assert e.strikeouts == 0.97


def test_hitter_hit_probability_increases_with_pa():
    assert hitter_hit_probability(per_pa_hit_prob=.25, projected_pa=4.5) > hitter_hit_probability(per_pa_hit_prob=.25, projected_pa=3.0)


def test_total_bases_respond_more_to_xbh_and_hr_environment():
    neutral = EnvironmentEffects()
    boosted = EnvironmentEffects(hr=1.20, xbh=1.25, runs=1.0, strikeouts=1.0)
    assert total_bases_mean(per_pa_tb=.42, projected_pa=4.2, env=boosted) > total_bases_mean(per_pa_tb=.42, projected_pa=4.2, env=neutral)


def test_strikeout_environment_only_moves_k_projection():
    neutral = EnvironmentEffects()
    low_k = EnvironmentEffects(strikeouts=.90)
    assert strikeout_mean(k_rate=.28, projected_batters_faced=23, env=low_k) < strikeout_mean(k_rate=.28, projected_batters_faced=23, env=neutral)


def test_hits_allowed_uses_contact_environment_mix():
    neutral = EnvironmentEffects()
    hitter_env = EnvironmentEffects(hr=1.2, xbh=1.2, runs=1.2)
    assert hits_allowed_mean(xba_allowed=.245, projected_batters_faced=24, env=hitter_env) > hits_allowed_mean(xba_allowed=.245, projected_batters_faced=24, env=neutral)


def test_poisson_half_line_has_no_push_and_sums_to_one():
    p = poisson_line(5.1, 4.5, market="PITCHER_K")
    assert p.push_prob == 0
    assert abs(p.over_prob + p.under_prob - 1) < 1e-9
    assert p.promotion_evidence is False


def test_poisson_integer_line_exposes_push():
    p = poisson_line(5.1, 5.0, market="PITCHER_K")
    assert p.push_prob > 0
    assert abs(p.over_prob + p.under_prob + p.push_prob - 1) < 1e-9


def test_recorded_outs_mean_is_structural_not_recent_streak():
    assert recorded_outs_mean(projected_batters_faced=24, non_out_rate=.31) == 24 * .69
