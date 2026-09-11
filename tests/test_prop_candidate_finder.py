from sportsedge.mlb.prop_candidate_finder import (
    CandidateType, Signal, bullpen_attack_signals, hitter_hit_signals,
    make_candidate, pitcher_hits_allowed_signals, score_signals,
)


def test_missing_inputs_reduce_coverage_and_fail_closed():
    score, coverage = score_signals([Signal("a", .9, 1, True), Signal("b", .9, 2, False)], min_coverage=.5)
    assert score == 0.0
    assert coverage < .5


def test_recent_streak_cannot_carry_hitter_candidate_alone():
    f = {"recent_hit_rate": 1.0, "projected_pa_score": .45, "lineup_slot_score": .45,
         "contact_score": .45, "platoon_score": .45, "sp_xba_allowed_score": .45,
         "bullpen_attack_score": .45, "environment_score": .45}
    assert make_candidate(CandidateType.HITTER_HIT, "H", "P", hitter_hit_signals(f)) is None


def test_hitter_candidate_requires_structural_support():
    f = {"recent_hit_rate": .9, "projected_pa_score": .9, "lineup_slot_score": .85,
         "contact_score": .8, "platoon_score": .75, "sp_xba_allowed_score": .8,
         "bullpen_attack_score": .7, "environment_score": .65}
    c = make_candidate(CandidateType.HITTER_HIT, "H", "P", hitter_hit_signals(f))
    assert c is not None
    assert c.promotion_evidence is False


def test_hits_allowed_recent_rate_is_only_small_weight():
    s = pitcher_hits_allowed_signals({"recent_4plus_rate": 1.0, "bf_score": .4, "xba_allowed_score": .4,
        "hard_hit_score": .4, "barrel_score": .4, "opp_contact_score": .4, "opp_hand_score": .4})
    assert next(x for x in s if x.name == "recent_4plus").weight < next(x for x in s if x.name == "xba_allowed").weight


def test_bullpen_last7_era_is_not_primary_signal():
    s = bullpen_attack_signals({"season_xfip_score": .8, "last14_xfip_score": .8,
        "reliever_unavailable_score": .8, "back_to_back_score": .8,
        "platoon_fit_score": .8, "last7_era_score": 1.0})
    assert next(x for x in s if x.name == "last7_era").weight == .20
    assert next(x for x in s if x.name == "availability").weight > 1.0
