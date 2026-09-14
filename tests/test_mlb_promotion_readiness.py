import unittest

from sportsedge.edge_floors import DEFAULT_EDGE_FLOOR_CONFIG, load_edge_floor_config
from sportsedge.mlb_promotion_readiness import (
    _floor_readiness,
    _predeployment_complete,
    build_mlb_promotion_readiness,
)


BASE_CONFIG = {
    "truth_gate": {
        "schema_version": 2,
        "production": {
            "fail_closed": True,
            "allow_cli_floor_override": False,
            "require_frozen_floor_for_eligible_market": True,
        },
        "devig_policy": {
            "policy_id": "EDGE_FLOOR_DEVIG_V1",
            "status": "FROZEN_PRE_DERIVATION",
            "longshot_trigger_american_odds": 400,
            "longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
            "sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],
            "sensitivity_limit_absolute_probability_points": 0.01,
            "stable_candidate_estimator": "POWER_V1",
            "longshot_candidate_estimator": "POWER_V1",
            "haircut_probability_points": 0.0,
            "aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
            "sensitivity_failure": "BLOCK",
        },
        "edge_floors": {},
    }
}


class MLBPromotionReadinessTests(unittest.TestCase):
    def test_missing_floor_fails_closed(self):
        row = _floor_readiness(market="MONEYLINE", config=BASE_CONFIG)
        self.assertFalse(row["frozen"])
        self.assertIn("MISSING_OR_UNFROZEN_EDGE_FLOOR", row["blocker"])

    def test_valid_frozen_floor_has_bound_evidence(self):
        config = {
            **BASE_CONFIG,
            "truth_gate": {
                **BASE_CONFIG["truth_gate"],
                "edge_floors": {
                    "MONEYLINE": {
                        "status": "FROZEN",
                        "value_probability_points": 0.03,
                        "method_version": "TEST_ONLY_V1",
                        "evidence": {
                            "evidence_sha256": "a" * 64,
                            "derivation_code_sha256": "b" * 64,
                            "oos_cutoff_utc": "2026-09-01T00:00:00Z",
                        },
                        "frozen": {"frozen_by_commit": "c" * 40},
                    }
                },
            },
        }
        row = _floor_readiness(market="MONEYLINE", config=config)
        self.assertTrue(row["frozen"])
        self.assertEqual(row["value_probability_points"], "0.03")
        self.assertEqual(row["evidence_sha256"], "a" * 64)
        self.assertIsNone(row["blocker"])

    def test_v3_default_floor_resolution_is_explicitly_mlb(self):
        config = load_edge_floor_config(DEFAULT_EDGE_FLOOR_CONFIG)
        row = _floor_readiness(market="MONEYLINE", config=config)
        self.assertTrue(row["frozen"])
        self.assertIsNone(row["blocker"])

    def test_predeployment_complete_excludes_only_final_eligibility_switch(self):
        row = {
            "current_state": {
                "runtime_engine": True,
                "registered": True,
                "eligible": False,
                "behavioral_status": "KEEP_MEASURED",
                "feature_realization_status": "COMPLETE",
                "validation_missing": [],
            },
            "acceptance_complete": False,
        }
        self.assertTrue(_predeployment_complete(row))
        self.assertFalse(row["acceptance_complete"])

    def test_predeployment_fails_closed_on_any_evidence_or_feature_gap(self):
        base = {
            "runtime_engine": True,
            "registered": True,
            "behavioral_status": "KEEP_MEASURED",
            "feature_realization_status": "COMPLETE",
            "validation_missing": [],
        }
        for key, value in (
            ("runtime_engine", False),
            ("registered", False),
            ("behavioral_status", "FIX"),
            ("feature_realization_status", "PARTIAL"),
            ("validation_missing", ["calibration"]),
        ):
            state = dict(base)
            state[key] = value
            self.assertFalse(_predeployment_complete({"current_state": state}), key)

    def test_default_inventory_never_reports_official_without_floor_or_predeployment(self):
        report = build_mlb_promotion_readiness()
        self.assertGreater(report["market_count"], 0)
        for row in report["markets"]:
            if row["official_ready"]:
                self.assertTrue(row["edge_floor"]["frozen"])
                self.assertTrue(row["predeployment_complete"])
                self.assertTrue(row["acceptance_complete"])
                self.assertTrue(row["deployment_eligible"])

    def test_audit_has_zero_authority(self):
        report = build_mlb_promotion_readiness()
        authority = report["authority"]
        self.assertTrue(authority["diagnostic_only"])
        for key in (
            "model_p_authority",
            "promotion_authority",
            "eligibility_authority",
            "official_authority",
            "floor_freeze_authority",
        ):
            self.assertFalse(authority[key], key)


if __name__ == "__main__":
    unittest.main()
