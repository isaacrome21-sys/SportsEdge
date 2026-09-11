import json
from pathlib import Path

from sports.common.promotion_evidence import clustered_mean_ci, evaluate_promotion, normalize_state


POLICY = Path("config/promotion_evidence_policy_v2.json")
MANIFEST = Path("config/promotion_evidence_policy_manifest.json")


def load_policy():
    return json.loads(POLICY.read_text())


def load_manifest():
    return json.loads(MANIFEST.read_text())


def metrics(n, *, mean=0.01, lo=0.001, hi=0.02, coverage=0.95, roi=0.0,
            games=50, clusters=12, drawdown=0.0):
    return {
        "graded_bets": n,
        "distinct_games": games,
        "slate_clusters": clusters,
        "close_coverage": coverage,
        "mean_clv_pp": mean,
        "clv_ci_lower_pp": lo,
        "clv_ci_upper_pp": hi,
        "roi_fraction": roi,
        "lane_drawdown_from_peak_units": drawdown,
        "integrity_failures": [],
    }


def prereqs():
    return {
        "frozen_lane_definition": True,
        "genuine_model_p_from_frozen_artifact": True,
        "working_two_sided_pregame_capture": True,
        "working_two_sided_close_capture": True,
    }


def eval_at(m, state="PAPER", warnings=()):
    return evaluate_promotion(
        m,
        current_state=state,
        prerequisites=prereqs(),
        warnings=warnings,
        policy=load_policy(),
        manifest=load_manifest(),
        git_ref="refs/heads/main",
    )


def test_policy_activates_only_on_main_manifest():
    p, manifest = load_policy(), load_manifest()
    blocked = evaluate_promotion(
        metrics(50), current_state="PAPER", prerequisites=prereqs(), warnings=(),
        policy=p, manifest=manifest, git_ref="refs/heads/feature"
    )
    assert blocked["state"] == "BLOCKED"
    assert blocked["decision"] == "POLICY_NOT_ACTIVE_ON_EVIDENCE_REF"


def test_trial_alias_folds_to_probation_without_relabelling_old_evidence():
    assert normalize_state("TRIAL", load_policy()) == "PROBATION"
    r = eval_at(metrics(51), state="TRIAL")
    assert r == {"state": "PROBATION", "decision": "NO_FIXED_CHECKPOINT", "graded_bets": 51}


def test_checkpoint_50_enters_probation_without_redundant_ci_upper_promotion_rule():
    p = load_policy()
    assert "clv_ci_upper_pp_must_be_above" not in p["checkpoints"]["checkpoint_50"]
    r = eval_at(metrics(50, mean=0.0, lo=-0.02, hi=0.01))
    assert r["state"] == "PROBATION"


def test_checkpoint_100_cannot_backdoor_probation_entry():
    r = eval_at(metrics(100), state="PAPER")
    assert r["state"] == "PAPER"
    assert r["decision"] == "PROBATION_ENTRY_CHECKPOINT_MISSED"


def test_checkpoint_150_needs_positive_lower_bound_and_resolved_warnings():
    unresolved = eval_at(metrics(150), state="PROBATION", warnings=({"status": "OPEN"},))
    assert unresolved["state"] == "PROBATION"
    assert unresolved["decision"] == "OFFICIAL_WARNINGS_UNRESOLVED"
    promoted = eval_at(metrics(150), state="PROBATION", warnings=({"status": "CLEARED"},))
    assert promoted["state"] == "OFFICIAL"


def test_signed_off_warning_requires_audit_fields():
    bad = eval_at(metrics(150), state="PROBATION", warnings=({"status": "SIGNED_OFF", "actor": "x"},))
    assert bad["state"] == "PROBATION"
    good_warning = {
        "status": "SIGNED_OFF", "actor": "x", "timestamp_utc": "2026-09-11T00:00:00Z",
        "reason": "accepted", "evidence_reference": "sha256:abc"
    }
    assert eval_at(metrics(150), state="PROBATION", warnings=(good_warning,))["state"] == "OFFICIAL"


def test_integrity_and_drawdown_fail_closed():
    m = metrics(50)
    m["integrity_failures"] = ["EVIDENCE_ROW_NOT_BOUND_TO_POLICY_SHA256"]
    assert eval_at(m)["state"] == "BLOCKED"
    assert eval_at(metrics(50, drawdown=5.0))["state"] == "PAPER"


def test_cr1_uses_student_t_g_minus_1():
    ci = clustered_mean_ci([0.01, 0.02, 0.00, 0.03, -0.01], ["a", "b", "c", "d", "e"])
    assert ci.clusters == 5
    assert ci.df == 4
    assert "STUDENT_T_G_MINUS_1" in ci.method
    normal_half = 1.959964 * ci.standard_error
    assert (ci.upper - ci.mean) > normal_half


def test_fixed_checkpoint_kills():
    assert eval_at(metrics(50, coverage=0.89))["decision"] == "CHECKPOINT_KILL_CLOSE_COVERAGE"
    assert eval_at(metrics(50, roi=-0.08))["decision"] == "CHECKPOINT_KILL_ROI"
    assert eval_at(metrics(50, mean=-0.02, lo=-0.03, hi=-0.001))["decision"] == "CHECKPOINT_KILL_NEGATIVE_CLV_INTERVAL"


def test_nonretroactive_legacy_rule_is_frozen():
    p = load_policy()
    assert p["non_retroactive"]["legacy_2026_nfl_confirmation_run"] == \
        "REMAINS_UNDER_PRIOR_POLICY_AND_CANNOT_BE_RECLASSIFIED_BY_V2"
