import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.sports.cfb.reconstructed_selection_acquisition import (
    CFBAcquisitionError,
    RequestSpec,
    acquire_one,
    build_public_manifest,
    build_request_plan,
    load_budget,
    validate_private_preflight,
)

ROOT = Path(__file__).resolve().parents[1]
BUDGET = ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json"


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class TestCFBReconstructedSelectionAcquisition(unittest.TestCase):
    def private_preflight(self):
        return {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
            "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL",
            "active_cfbd_tier": "TIER_1",
            "patron_level": 1,
            "monthly_quota": 5000,
            "remaining_quota": 1000,
            "planned_new_calls": 254,
            "retry_reserve_calls": 50,
            "weather_entitled": True,
            "verified_cache_reuse": True,
            "resume_from_verified_cache": True,
            "restart_from_2015": False,
            "retry_backoff": True,
            "historical_replay_calls_performed": 0,
            "blockers": [],
            "authority": {
                "attempt_consumed": False,
                "evaluation_performed": False,
                "model_p": False,
                "truth_gate": False,
                "promotion": False,
                "eligibility": False,
                "staking": False,
                "official": False,
                "backfill": False,
            },
        }

    def public_preflight(self):
        return {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_PUBLIC_V1",
            "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL",
            "account_info_verified": True,
            "standard_tier_mapping_verified": True,
            "weather_entitled": True,
            "call_plan_fits": True,
            "historical_replay_calls_performed": 0,
            "blockers": [],
            "authority": {
                "attempt_consumed": False,
                "evaluation_performed": False,
                "model_p": False,
                "truth_gate": False,
                "promotion": False,
                "eligibility": False,
                "staking": False,
                "official": False,
                "backfill": False,
            },
        }

    def test_frozen_plan_has_exact_budget_shape(self):
        plan = build_request_plan(load_budget(BUDGET))
        self.assertEqual(len(plan), 254)
        counts = {
            endpoint: sum(1 for row in plan if row.endpoint == endpoint)
            for endpoint in {row.endpoint for row in plan}
        }
        self.assertEqual(counts["/games"], 12)
        self.assertEqual(counts["/teams/fbs"], 11)
        self.assertEqual(counts["/games/weather"], 11)
        self.assertEqual(counts["/stats/season/advanced"], 220)
        advanced = [row for row in plan if row.endpoint == "/stats/season/advanced"]
        self.assertEqual(sum(row.season == 2014 and row.end_week == 20 for row in advanced), 1)
        self.assertEqual(sum(row.season == 2025 and row.end_week == 19 for row in advanced), 1)

    def test_private_preflight_blocks_when_budget_no_longer_fits(self):
        report = self.private_preflight()
        report["remaining_quota"] = 303
        with self.assertRaisesRegex(CFBAcquisitionError, "BUDGET_NO_LONGER_FITS"):
            validate_private_preflight(report)

    def test_acquire_one_persists_projection_not_raw_and_reuses_verified_cache(self):
        spec = RequestSpec(
            endpoint="/stats/season/advanced",
            season=2025,
            end_week=3,
            provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            query=(("endWeek", "3"), ("year", "2025")),
        )
        payload = [{
            "season": 2025,
            "team": "Example",
            "conference": "Test",
            "offense": {
                "ppa": 0.1,
                "successRate": 0.4,
                "explosiveness": 1.0,
                "drives": 20,
                "totalOpportunies": 8,
                "pointsPerOpportunity": 4.1,
                "rushingPlays": {"ppa": 0.2, "successRate": 0.5},
                "passingPlays": {"ppa": 0.3, "successRate": 0.4},
                "standardDowns": {"ppa": 0.25, "successRate": 0.48},
                "passingDowns": {"ppa": 0.15, "successRate": 0.31},
                "fieldPosition": {"averageStart": 31.2},
                "secretExtraField": "do-not-project",
            },
            "defense": {
                "ppa": -0.1,
                "successRate": 0.35,
                "explosiveness": 0.8,
                "drives": 19,
                "totalOpportunies": 6,
                "pointsPerOpportunity": 3.0,
                "rushingPlays": {"ppa": -0.2, "successRate": 0.3},
                "passingPlays": {"ppa": -0.1, "successRate": 0.4},
                "standardDowns": {"ppa": -0.12, "successRate": 0.34},
                "passingDowns": {"ppa": -0.08, "successRate": 0.32},
                "fieldPosition": {"averageStart": 27.4},
            },
        }]
        calls = []

        def opener(request, timeout=30):
            calls.append((request.full_url, timeout))
            return _Response(payload)

        with tempfile.TemporaryDirectory() as td:
            cache_root = Path(td)
            first, reused = acquire_one(
                spec,
                api_key="test-key",
                cache_root=cache_root,
                opener=opener,
                sleep=lambda _: None,
                now=lambda: datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
            )
            self.assertFalse(reused)
            self.assertEqual(len(calls), 1)
            self.assertFalse(first["raw_response_persisted"])
            self.assertNotIn("secretExtraField", json.dumps(first["projection"]))
            second, reused = acquire_one(
                spec,
                api_key="test-key",
                cache_root=cache_root,
                opener=lambda *a, **k: self.fail("network should not be called on verified cache reuse"),
                sleep=lambda _: None,
            )
            self.assertTrue(reused)
            self.assertEqual(first["response_sha256"], second["response_sha256"])

    def test_public_manifest_redacts_exact_account_quota_values(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private = root / "private.json"
            public = root / "public.json"
            private.write_text(json.dumps(self.private_preflight()), encoding="utf-8")
            public.write_text(json.dumps(self.public_preflight()), encoding="utf-8")
            manifest = build_public_manifest(
                private_preflight_path=private,
                public_preflight_path=public,
                budget_path=BUDGET,
                cache_manifest=[],
                reused_calls=0,
                fetched_calls=0,
            )
            encoded = json.dumps(manifest, sort_keys=True)
            self.assertTrue(manifest["account_tier_verified_privately"])
            self.assertTrue(manifest["remaining_quota_verified_privately"])
            self.assertFalse(manifest["exact_account_quota_values_published"])
            self.assertNotIn("TIER_1", encoded)
            self.assertNotIn('"remaining_quota"', encoded)
            self.assertNotIn('"monthly_quota"', encoded)
            self.assertTrue(all(value is False for value in manifest["authority"].values()))


if __name__ == "__main__":
    unittest.main()
