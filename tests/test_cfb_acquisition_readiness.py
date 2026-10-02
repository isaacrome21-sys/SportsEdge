import json
import unittest
from pathlib import Path

from sportsedge.sports.cfb.acquisition_readiness import audit_cfb_acquisition_readiness

ROOT = Path(__file__).resolve().parents[1]


def cache_entry():
    return {
        "endpoint": "/stats/season/advanced",
        "season": 2025,
        "end_week": 3,
        "provider_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        "query_sha256": "a" * 64,
        "response_sha256": "b" * 64,
        "retrieved_at_utc": "2026-09-12T20:00:00+00:00",
    }


class TestCFBAcquisitionReadiness(unittest.TestCase):
    def policy(self):
        return json.loads((ROOT / "config/cfb_model_selection_policy_v1.json").read_text())

    def verified(self):
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
            "cache_manifest": [cache_entry()],
        }

    def test_missing_manifest_blocks_without_spending_attempt(self):
        out = audit_cfb_acquisition_readiness(self.policy(), None)
        self.assertEqual(out["status"], "BLOCKED_ACQUISITION_NOT_VERIFIED")
        self.assertIn("ACQUISITION_MANIFEST_MISSING", out["blockers"])
        self.assertFalse(out["network_call_performed"])
        self.assertFalse(out["attempt_consumed"])
        self.assertFalse(out["model_fit_performed"])

    def test_verified_manifest_allows_replay_start_only(self):
        out = audit_cfb_acquisition_readiness(self.policy(), self.verified())
        self.assertEqual(out["status"], "READY_FOR_HISTORICAL_REPLAY")
        self.assertEqual(out["blockers"], [])
        self.assertFalse(out["model_p_created"])
        self.assertFalse(out["promotion_authority"])

    def test_call_plan_must_fit_remaining_quota_plus_reserve(self):
        manifest = self.verified()
        manifest["planned_new_calls"] = 790
        out = audit_cfb_acquisition_readiness(self.policy(), manifest)
        self.assertIn("CALL_PLAN_EXCEEDS_VERIFIED_REMAINING_QUOTA", out["blockers"])

    def test_cache_requires_hash_and_timestamp_provenance(self):
        manifest = self.verified()
        manifest["cache_manifest"][0]["response_sha256"] = None
        manifest["cache_manifest"][0]["retrieved_at_utc"] = None
        out = audit_cfb_acquisition_readiness(self.policy(), manifest)
        self.assertIn("CACHE_RESPONSE_SHA256_INVALID:0", out["blockers"])
        self.assertIn("CACHE_RETRIEVAL_TIMESTAMP_MISSING:0", out["blockers"])


    def public_verified(self):
        return {
            "schema": "CFB_RECONSTRUCTED_ACQUISITION_READINESS_PUBLIC_V1",
            "status": "ACQUISITION_COMPLETE_READY_FOR_SELECTION",
            "account_info_verified": True,
            "tier_quota_mapping_verified": True,
            "call_plan_fits_verified_quota": True,
            "planned_new_calls": 100,
            "retry_reserve_calls": 25,
            "verified_cache_reuse": True,
            "resume_from_verified_cache": True,
            "restart_from_2015": False,
            "retry_backoff": True,
            "source_manifest_sha256": "c" * 64,
            "preflight_proof_sha256": "d" * 64,
            "cache_manifest": [
                cache_entry(),
                {
                    "endpoint": "/venues",
                    "season": None,
                    "end_week": None,
                    "provider_contract": "CFBD_VENUES_LOCATION_DOME_V1",
                    "query_sha256": "e" * 64,
                    "response_sha256": "f" * 64,
                    "retrieved_at_utc": "2026-09-12T20:00:00+00:00",
                },
            ],
            "authority": {
                "attempt_consumed": False,
                "evaluation_performed": False,
                "historical_pit_created": False,
                "model_p_created": False,
                "truth_gate_authority": False,
                "promotion_authority": False,
                "staking_authority": False,
                "eligibility_changed": False,
                "official_authority": False,
                "backfill": False,
            },
        }

    def test_redacted_public_proof_allows_readiness_without_exposing_quota_values(self):
        out = audit_cfb_acquisition_readiness(self.policy(), self.public_verified())
        self.assertEqual(out["status"], "READY_FOR_HISTORICAL_REPLAY")
        self.assertEqual(out["blockers"], [])
        self.assertTrue(out["public_proof"])
        self.assertIsNone(out["monthly_quota"])
        self.assertIsNone(out["remaining_quota"])
        self.assertEqual(out["verified_cache_entries"], 2)

    def test_redacted_public_proof_fails_closed_on_unverified_quota_fit(self):
        manifest = self.public_verified()
        manifest["call_plan_fits_verified_quota"] = False
        out = audit_cfb_acquisition_readiness(self.policy(), manifest)
        self.assertIn("CALL_PLAN_QUOTA_FIT_UNVERIFIED", out["blockers"])

    def test_redacted_public_proof_rejects_authority_leak(self):
        manifest = self.public_verified()
        manifest["authority"]["promotion_authority"] = True
        out = audit_cfb_acquisition_readiness(self.policy(), manifest)
        self.assertIn("PUBLIC_ACQUISITION_AUTHORITY_LEAK", out["blockers"])

    def test_full_restart_from_2015_is_explicitly_blocked(self):
        manifest = self.verified()
        manifest["restart_from_2015"] = True
        out = audit_cfb_acquisition_readiness(self.policy(), manifest)
        self.assertIn("FULL_RESTART_FROM_2015_PROHIBITED", out["blockers"])


if __name__ == "__main__":
    unittest.main()
