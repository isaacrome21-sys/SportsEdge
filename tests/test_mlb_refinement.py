import pytest

from sportsedge.mlb_refinement import (
    MLBRefinementError,
    assert_unique_ladder,
    conflict_assessment,
    first_inning_hazard,
    pitcher_k_expectation,
    research_adjusted_edge,
    starter_leash,
    weather_effects,
)


def _quote(line, odds):
    return {
        "market": "TOTAL_BASES",
        "entity_name": "Example Batter",
        "side": "OVER",
        "line": line,
        "american_odds": odds,
        "sportsbook": "DraftKings",
        "retrieved_at": "2026-08-20T16:03:59+00:00",
    }


def test_ladder_identity_keeps_exact_threshold_and_price():
    rows = assert_unique_ladder([_quote(0.5, -190), _quote(1.5, 134), _quote(2.5, 260)])
    assert [(r.line, r.american_odds) for r in rows] == [(0.5, -190), (1.5, 134), (2.5, 260)]


def test_ladder_conflicting_price_fails_closed():
    with pytest.raises(MLBRefinementError, match="AMBIGUOUS_LADDER_PRICE"):
        assert_unique_ladder([_quote(1.5, 134), _quote(1.5, 120)])


def test_nrfi_hazard_increases_with_dangerous_top_order():
    low = first_inning_hazard(
        top3_xwoba=.285, top3_iso=.120, top3_bb_rate=.070, top3_barrel_rate=.045,
        starter_first_inning_bb_rate=.060, starter_first_inning_hr_rate=.015,
        starter_first_time_through_woba=.285, platoon_advantage_share=.33,
        first_inning_power_index=.90, lineup_confirmed=True,
    )
    high = first_inning_hazard(
        top3_xwoba=.390, top3_iso=.240, top3_bb_rate=.120, top3_barrel_rate=.120,
        starter_first_inning_bb_rate=.120, starter_first_inning_hr_rate=.055,
        starter_first_time_through_woba=.380, platoon_advantage_share=.67,
        first_inning_power_index=1.18, lineup_confirmed=True,
    )
    assert high.hazard_score > low.hazard_score


def test_projected_lineup_never_strengthens_nrfi_diagnostic():
    kwargs = dict(
        top3_xwoba=.320, top3_iso=.160, top3_bb_rate=.085, top3_barrel_rate=.070,
        starter_first_inning_bb_rate=.085, starter_first_inning_hr_rate=.030,
        starter_first_time_through_woba=.320, platoon_advantage_share=.50,
        first_inning_power_index=1.0,
    )
    confirmed = first_inning_hazard(**kwargs, lineup_confirmed=True)
    projected = first_inning_hazard(**kwargs, lineup_confirmed=False)
    assert projected.hazard_score >= confirmed.hazard_score


def test_starter_leash_rewards_pitch_ceiling_and_efficiency():
    long = starter_leash(
        avg_pitches_3=99, max_pitches_5=108, starts_95plus_10=.80,
        pitches_per_pa_5=3.55, outs_per_start_5=19.5,
        bullpen_rest_index=.30, manager_hook_index=.25,
    )
    short = starter_leash(
        avg_pitches_3=78, max_pitches_5=91, starts_95plus_10=.10,
        pitches_per_pa_5=4.35, outs_per_start_5=14.2,
        bullpen_rest_index=.80, manager_hook_index=.75,
    )
    assert long.leash_score > short.leash_score


def test_pitcher_k_expectation_is_batters_faced_times_matchup_k_rate():
    result = pitcher_k_expectation(
        expected_batters_faced=24,
        batter_k_probabilities=[.20, .30, .25],
        batter_pa_weights=[1, 1, 2],
        pitch_quality_multiplier=1.10,
    )
    assert result.batter_weighted_k_probability == pytest.approx(.25)
    assert result.expected_strikeouts == pytest.approx(6.6)


def test_weather_splits_run_and_power_effects_and_roof_kills_wind():
    open_air = weather_effects(
        park_run_factor=1.02, park_hr_factor=1.08, temperature_f=90,
        wind_out_mph=12, humidity_pct=55, roof_closed=False,
    )
    roof = weather_effects(
        park_run_factor=1.02, park_hr_factor=1.08, temperature_f=90,
        wind_out_mph=12, humidity_pct=55, roof_closed=True,
    )
    assert open_air.first_inning_power_index > roof.first_inning_power_index
    assert open_air.run_environment_index > roof.run_environment_index


def test_conflicts_only_reduce_confidence():
    clean = conflict_assessment(nrfi_requested=True, hitter_attack_signal=.20,
                                first_inning_hazard_score=.35, lineup_confirmed=True)
    conflicted = conflict_assessment(nrfi_requested=True, hitter_attack_signal=.90,
                                     first_inning_hazard_score=.80,
                                     model_disagreement=.50, lineup_confirmed=False,
                                     weather_source_disagreement=.60)
    assert clean.confidence_multiplier == 1.0
    assert conflicted.confidence_multiplier < clean.confidence_multiplier
    assert "NRFI_HITTER_ATTACK_CONFLICT" in conflicted.flags


def test_research_adjusted_edge_cannot_create_edge():
    assert research_adjusted_edge(model_probability=.55, fair_market_probability=.50,
                                  confidence_multiplier=.70) == pytest.approx(.035)
    assert research_adjusted_edge(model_probability=.48, fair_market_probability=.50,
                                  confidence_multiplier=.70) == pytest.approx(-.014)
