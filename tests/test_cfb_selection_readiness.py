import json
import unittest
from pathlib import Path

from sportsedge.sports.cfb.acquisition_readiness import audit_cfb_acquisition_readiness
from sportsedge.sports.cfb.model_selection_prereg import audit_model_selection_prereg
from sportsedge.sports.cfb.selection_readiness import audit_cfb_selection_readiness

ROOT = Path(__file__).resolve().parents[1]


class TestCFBSelectionReadiness(unittest.TestCase):
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

    def audit(self, acquisition_manifest=None, bundle=None, freeze=None):
        acquisition = audit_cfb_acquisition_readiness(self.policy, acquisition_manifest)
        return audit_cfb_selection_readiness(
            policy=self.policy,
            preregistration=self.prereg,
            prereg_report=self.prereg_report,
            freeze_registry=self.freeze if freeze is None else freeze,
            acquisition_report=acquisition,
            selection_bundle=bundle,
        )

    def test_missing_reconstructed_inputs_block_without_pit_dependency(self):
        out = self.audit()
        self.assertFalse(out["first_evaluation_allowed"])
        self.assertIn("RECONSTRUCTED_ACQUISITION_NOT_READY", out["blockers"])
        self.assertIn("RECONSTRUCTED_SELECTION_BUNDLE_MISSING", out["blockers"])
        self.assertFalse(out["historical_pit_required_for_selection"])
        self.assertNotIn("GENUINE_PIT_SOURCE_CONTRACT_NOT_READY", out["blockers"])

    def test_ready_reconstructed_lane_allows_attempt_one_only(self):
        out = self.audit(self.acquisition_manifest(), self.bundle())
        self.assertTrue(out["first_evaluation_allowed"])
        self.assertEqual(out["status"], "FIRST_EVALUATION_ALLOWED")
        self.assertFalse(out["historical_pit_created"])
        self.assertFalse(out["model_p_created"])
        self.assertFalse(out["promotion_authority"])
        self.assertFalse(out["official_authority"])

    def test_truth_gate_state_is_not_a_selection_input(self):
        manifest = self.acquisition_manifest()
        manifest["historical_truth_gate_execution_allowed"] = False
        bundle = self.bundle()
        bundle["historical_truth_gate_execution_allowed"] = False
        out = self.audit(manifest, bundle)
        self.assertTrue(out["first_evaluation_allowed"])

    def test_weather_provenance_must_be_explicit_for_weather_features(self):
        bundle = self.bundle()
        bundle["weather_provenance_class"] = "UNRESOLVED"
        out = self.audit(self.acquisition_manifest(), bundle)
        self.assertFalse(out["first_evaluation_allowed"])
        self.assertIn("SELECTION_BUNDLE_WEATHER_PROVENANCE_UNRESOLVED", out["blockers"])

    def test_promotion_authority_leak_blocks_selection_gate(self):
        freeze = dict(self.freeze)
        freeze["promotion_authority"] = True
        out = self.audit(self.acquisition_manifest(), self.bundle(), freeze=freeze)
        self.assertFalse(out["first_evaluation_allowed"])
        self.assertIn("FREEZE_REGISTRY_PROMOTION_AUTHORITY_MUST_BE_FALSE", out["blockers"])


if __name__ == "__main__":
    unittest.main()
