import json
import unittest
from pathlib import Path

from sportsedge.sports.cfb.acquisition_readiness import audit_cfb_acquisition_readiness
from sportsedge.sports.cfb.model_selection_prereg import audit_model_selection_prereg
from sportsedge.sports.cfb.selection_readiness import audit_cfb_selection_readiness

ROOT = Path(__file__).resolve().parents[1]


class TestCFBModelSelectionReadiness(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "config/cfb_model_selection_policy_v1.json").read_text())
        self.prereg = json.loads((ROOT / "config/cfb_model_candidate_prereg_v1.json").read_text())
        self.freeze = json.loads((ROOT / "config/cfb_game_model_freeze.json").read_text())
        self.prereg_report = audit_model_selection_prereg(self.policy, self.prereg)

    def acquisition_manifest(self):
        return {
            "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL",
            "active_cfbd_tier": "VERIFIED_ACCOUNT_TIER",
            "monthly_quota": 1000,
            "remaining_quota": 800,
            "planned_new_calls": 100,
            "retry_reserve_calls": 25,
            "verified_cache_reuse": True,
            "resume_from_verified_cache": True,
            "restart_from_2015": False,
            "retry_backoff": True,
            "cache_manifest": [{
                "endpoint": "/stats/season/advanced",
                "season": 2025,
                "end_week": 3,
                "provider_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
                "query_sha256": "a" * 64,
                "response_sha256": "b" * 64,
                "retrieved_at_utc": "2026-09-12T20:00:00+00:00",
            }],
        }

    def bundle(self):
        return {
            "schema": "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1",
            "status": "READY_FOR_CANDIDATE_EVALUATION",
            "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
            "feature_semantics": "AS_OF_WEEK_MATCHED_V1",
            "feature_value_source_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            "provider_metric_model_vintage": "UNKNOWN_CURRENT_PROVIDER_VINTAGE",
            "provider_metric_materialization_mode": "UNKNOWN_PROVIDER_IMPLEMENTATION",
            "start_season": 2015,
            "end_season": 2025,
            "no_2026_forward_outcomes": True,
            "market_data_in_predictive_features": False,
            "selection_rows_sha256": "1" * 64,
            "source_manifest_sha256": "2" * 64,
            "predictive_code_manifest_sha256": "3" * 64,
            "acquisition_code_manifest_sha256": "4" * 64,
            "weather_provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
            "weather_source_contract": "EXPLICIT_RECONSTRUCTED_WEATHER_V1",
        }

    def audit(self, acquisition_manifest=None, bundle=None):
        acquisition = audit_cfb_acquisition_readiness(self.policy, acquisition_manifest)
        return audit_cfb_selection_readiness(
            policy=self.policy,
            preregistration=self.prereg,
            prereg_report=self.prereg_report,
            freeze_registry=self.freeze,
            acquisition_report=acquisition,
            selection_bundle=bundle,
        )

    def test_missing_reconstructed_inputs_fail_closed_without_spending_attempt(self):
        out = self.audit()
        self.assertFalse(out["first_evaluation_allowed"])
        self.assertEqual(out["status"], "BLOCKED_RECONSTRUCTED_SELECTION_CONTRACT")
        self.assertIn("RECONSTRUCTED_ACQUISITION_NOT_READY", out["blockers"])
        self.assertIn("RECONSTRUCTED_SELECTION_BUNDLE_MISSING", out["blockers"])
        self.assertEqual(out["attempts_consumed"], 0)
        self.assertFalse(out["evaluation_performed"])
        self.assertFalse(out["historical_pit_required_for_selection"])

    def test_complete_reconstructed_contract_allows_selection_only(self):
        out = self.audit(self.acquisition_manifest(), self.bundle())
        self.assertTrue(out["first_evaluation_allowed"])
        self.assertEqual(out["status"], "FIRST_EVALUATION_ALLOWED")
        for key in (
            "historical_pit_created", "model_p_created", "truth_gate_authority",
            "promotion_authority", "staking_authority", "evidence_clock_authority",
            "eligibility_changed", "official_authority",
        ):
            self.assertFalse(out[key])

    def test_incomplete_training_window_bundle_blocks(self):
        bundle = self.bundle()
        bundle["start_season"] = 2021
        out = self.audit(self.acquisition_manifest(), bundle)
        self.assertFalse(out["first_evaluation_allowed"])
        self.assertIn("SELECTION_BUNDLE_START_SEASON_MISMATCH", out["blockers"])

    def test_workflow_requires_reconstructed_gate(self):
        text = (ROOT / ".github/workflows/cfb-candidate-first-evaluation-readiness.yml").read_text()
        self.assertIn("audit_cfb_selection_readiness.py", text)
        self.assertIn("history/cfb/reconstructed-selection", text)
        self.assertIn("reconstructed_selection_readiness.json", text)
        self.assertIn("BLOCKED_RECONSTRUCTED_SELECTION_CONTRACT", text)


if __name__ == "__main__":
    unittest.main()
