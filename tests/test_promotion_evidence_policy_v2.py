import json
from pathlib import Path

POLICY = Path("config/promotion_evidence_policy_v2.json")
MANIFEST = Path("config/promotion_evidence_policy_manifest.json")


def load_policy():
    return json.loads(POLICY.read_text())


def test_state_semantics_are_distinct():
    p = load_policy()
    assert p["policy_id"] == "PROMOTION_EVIDENCE_POLICY_V2"
    assert p["states"]["PAPER"]["evidence_counts"] is True
    assert p["states"]["BLOCKED"]["evidence_counts"] is False
    assert p["states"]["PROBATION"]["stake_units_per_bet"] == 0.25
    assert p["state_aliases"]["TRIAL"] == "PROBATION"


def test_main_only_activation_and_nonretroactivity_are_frozen():
    p = load_policy()
    m = json.loads(MANIFEST.read_text())
    assert p["activation"]["evidence_ref"] == "refs/heads/main"
    assert m["evidence_ref"] == "refs/heads/main"
    assert m["active_policy_id"] == p["policy_id"]
    assert p["non_retroactive"]["legacy_2026_nfl_confirmation_run"] == \
        "REMAINS_UNDER_PRIOR_POLICY_AND_CANNOT_BE_RECLASSIFIED_BY_V2"


def test_fixed_checkpoints_and_forward_only_rule_are_frozen():
    p = load_policy()
    assert p["checkpoints"]["evaluate_only_at_graded_counts"] == [50, 100, 150]
    assert p["forward_capture"]["clv_inference"]["continuous_peeking_for_promotion"] is False
    assert "clv_ci_upper_pp_must_be_above" not in p["checkpoints"]["checkpoint_50"]


def test_small_cluster_reference_distribution_is_frozen():
    p = load_policy()
    inf = p["forward_capture"]["clv_inference"]
    assert inf["standard_error"] == "CR1_CLUSTER_BY_SLATE_DATE"
    assert inf["reference_distribution"] == "STUDENT_T_G_MINUS_1"
    assert inf["minimum_clusters_for_interval"] == 5


def test_close_coverage_and_official_rules_are_frozen():
    p = load_policy()
    assert p["forward_capture"]["close"]["min_close_coverage_for_probation_or_official"] == 0.90
    assert "checkpoint denominator" in p["forward_capture"]["close"]["missing_close_policy"]
    assert p["checkpoints"]["checkpoint_150"]["min_distinct_games"] == 40
    assert p["checkpoints"]["checkpoint_150"]["min_slate_clusters"] == 10
    assert p["checkpoints"]["checkpoint_150"]["clv_ci_lower_pp_must_be_above"] == 0.0


def test_kill_rules_and_exposure_caps_are_numeric():
    p = load_policy()
    assert "clv_95_ci_upper_pp < 0.0" in p["kill_and_demotion_rules"]["demote_to_paper_at_checkpoint_if"]
    assert "roi_fraction < -0.075" in p["kill_and_demotion_rules"]["demote_to_paper_at_checkpoint_if"]
    assert "lane_drawdown_from_peak_units >= 5.0" in p["kill_and_demotion_rules"]["risk_demote_immediately_if"]
    probation = p["exposure_caps"]["probation"]
    assert probation["stake_units_per_bet"] == 0.25
    assert probation["max_lane_exposure_units_per_slate"] == 2.0
    assert probation["max_all_probation_exposure_units_per_slate"] == 4.0
    assert probation["max_lane_drawdown_from_peak_units"] == 5.0


def test_warning_signoff_and_historical_adverse_evidence_are_frozen():
    p = load_policy()
    assert p["official_warning_signoff"]["allowed_statuses"] == ["CLEARED", "SIGNED_OFF"]
    assert p["official_warning_signoff"]["signed_off_requires"] == [
        "actor", "timestamp_utc", "reason", "evidence_reference"
    ]
    assert p["historical_adverse_evidence"]["nfl_box_score_model_2026"] == "PAPER"
