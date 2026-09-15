from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.mlb_promotion_readiness import (
    _floor_readiness,
    _pre_eligibility_acceptance_complete,
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

    def test_pre_eligibility_readiness_does_not_require_eligibility(self):
        state = {
            "runtime_engine": True,
            "registered": True,
            "eligible": False,
            "behavioral_status": "KEEP_MEASURED",
            "feature_realization_status": "COMPLETE",
            "validation_missing": [],
        }
        self.assertTrue(_pre_eligibility_acceptance_complete(state))
        state["feature_realization_status"] = "UNVERIFIED"
        self.assertFalse(_pre_eligibility_acceptance_complete(state))

    def test_official_reads_persisted_eligibility_and_canonical_acceptance(self):
        current_state = {
            "runtime_engine": True,
            "registered": True,
            "eligible": False,
            "behavioral_status": "KEEP_MEASURED",
            "feature_realization_status": "COMPLETE",
            "validation_missing": [],
        }
        finish = {
            "markets": [
                {
                    "market": "HITS",
                    "deployment_eligible": False,
                    "acceptance_complete": False,
                    "blockers": [],
                }
            ]
        }
        acceptance = {"markets": [{"market": "HITS", "current_state": current_state}]}
        frozen_floor = {
            "frozen": True,
            "value_probability_points": "0.03",
            "method_version": "TEST_ONLY_V1",
            "evidence_sha256": "a" * 64,
            "blocker": None,
        }

        with (
            patch("sportsedge.mlb_promotion_readiness.build_mlb_finish_line", return_value=finish),
            patch("sportsedge.mlb_promotion_readiness.build_acceptance_matrix", return_value=acceptance),
            patch("sportsedge.mlb_promotion_readiness.load_edge_floor_config", return_value=BASE_CONFIG),
            patch("sportsedge.mlb_promotion_readiness._floor_readiness", return_value=frozen_floor),
        ):
            report = build_mlb_promotion_readiness()
        row = report["markets"][0]
        self.assertTrue(row["promotion_prerequisites_complete"])
        self.assertFalse(row["deployment_eligible"])
        self.assertFalse(row["acceptance_complete"])
        self.assertFalse(row["official_ready"])

        finish["markets"][0]["deployment_eligible"] = True
        finish["markets"][0]["acceptance_complete"] = True
        current_state["eligible"] = True
        with (
            patch("sportsedge.mlb_promotion_readiness.build_mlb_finish_line", return_value=finish),
            patch("sportsedge.mlb_promotion_readiness.build_acceptance_matrix", return_value=acceptance),
            patch("sportsedge.mlb_promotion_readiness.load_edge_floor_config", return_value=BASE_CONFIG),
            patch("sportsedge.mlb_promotion_readiness._floor_readiness", return_value=frozen_floor),
        ):
            report = build_mlb_promotion_readiness()
        self.assertTrue(report["markets"][0]["official_ready"])

    def test_eligible_flag_alone_cannot_bypass_canonical_acceptance(self):
        state = {
            "runtime_engine": True,
            "registered": True,
            "eligible": True,
            "behavioral_status": "KEEP_MEASURED",
            "feature_realization_status": "COMPLETE",
            "validation_missing": [],
        }
        finish = {
            "markets": [
                {
                    "market": "HITS",
                    "deployment_eligible": True,
                    "acceptance_complete": False,
                    "blockers": [],
                }
            ]
        }
        acceptance = {"markets": [{"market": "HITS", "current_state": state}]}
        frozen_floor = {
            "frozen": True,
            "value_probability_points": "0.03",
            "method_version": "TEST_ONLY_V1",
            "evidence_sha256": "a" * 64,
            "blocker": None,
        }
        with (
            patch("sportsedge.mlb_promotion_readiness.build_mlb_finish_line", return_value=finish),
            patch("sportsedge.mlb_promotion_readiness.build_acceptance_matrix", return_value=acceptance),
            patch("sportsedge.mlb_promotion_readiness.load_edge_floor_config", return_value=BASE_CONFIG),
            patch("sportsedge.mlb_promotion_readiness._floor_readiness", return_value=frozen_floor),
        ):
            report = build_mlb_promotion_readiness()
        row = report["markets"][0]
        self.assertTrue(row["promotion_prerequisites_complete"])
        self.assertTrue(row["deployment_eligible"])
        self.assertFalse(row["official_ready"])
        self.assertIn("CANONICAL_ACCEPTANCE_INCOMPLETE", row["promotion_blockers"])

    def test_audit_does_not_mutate_deployment_registry(self):
        source = Path("config/deployments.json")
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "deployments.json"
            shutil.copyfile(source, copied)
            before = copied.read_bytes()
            build_mlb_promotion_readiness(deployments_path=copied)
            after = copied.read_bytes()
        self.assertEqual(after, before)

    def test_default_inventory_never_reports_official_without_floor(self):
        report = build_mlb_promotion_readiness()
        self.assertGreater(report["market_count"], 0)
        self.assertEqual(
            report["six_gate_complete_count"],
            report["pre_eligibility_acceptance_complete_count"],
        )
        for row in report["markets"]:
            if row["official_ready"]:
                self.assertTrue(row["edge_floor"]["frozen"])
                self.assertTrue(row["pre_eligibility_acceptance_complete"])
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
