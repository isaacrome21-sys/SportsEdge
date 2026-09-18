from __future__ import annotations

import io
import json
import unittest

from scripts.preflight_cfb_reconstructed_selection import evaluate_account, fetch_account_info


CONFIG = {
    "standard_tier_monthly_quotas": {"0": 1000, "1": 5000, "2": 30000, "3": 75000, "4": 125000, "5": 200000, "6": 500000},
    "tier_labels": {"0": "FREE", "1": "TIER_1", "2": "TIER_2", "3": "TIER_3", "4": "TIER_4", "5": "TIER_5", "6": "TIER_6"},
    "weather_min_patron_level": 1,
    "planned_new_calls_upper_bound": {"total": 244},
    "retry_reserve_calls": 50,
}


class _Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self):
        return self._raw


class TestCFBReconstructedSelectionPreflight(unittest.TestCase):
    def test_authenticated_tier_one_with_room_is_ready(self):
        private, public = evaluate_account({"patronLevel": 1, "remainingCalls": 4700}, CONFIG)
        self.assertEqual(private["status"], "VERIFIED_BEFORE_FIRST_REPLAY_CALL")
        self.assertEqual(private["active_cfbd_tier"], "TIER_1")
        self.assertEqual(private["monthly_quota"], 5000)
        self.assertEqual(private["planned_new_calls"], 244)
        self.assertEqual(private["retry_reserve_calls"], 50)
        self.assertTrue(public["call_plan_fits"])
        self.assertTrue(public["weather_entitled"])
        self.assertEqual(private["historical_replay_calls_performed"], 0)
        self.assertTrue(all(value is False for value in private["authority"].values()))

    def test_free_tier_blocks_before_weather_replay(self):
        private, public = evaluate_account({"patronLevel": 0, "remainingCalls": 900}, CONFIG)
        self.assertEqual(private["status"], "BLOCKED_PROVIDER_PREFLIGHT")
        self.assertIn("CFBD_WEATHER_ENDPOINT_REQUIRES_PATRON_TIER", private["blockers"])
        self.assertFalse(public["weather_entitled"])
        self.assertEqual(private["historical_replay_calls_performed"], 0)

    def test_remaining_quota_must_cover_plan_and_retry_reserve(self):
        private, _ = evaluate_account({"patronLevel": 1, "remainingCalls": 293}, CONFIG)
        self.assertIn("CFBD_REPLAY_PLAN_EXCEEDS_REMAINING_QUOTA", private["blockers"])
        self.assertEqual(private["status"], "BLOCKED_PROVIDER_PREFLIGHT")

    def test_unknown_or_special_tier_fails_closed(self):
        private, _ = evaluate_account({"patronLevel": 99, "remainingCalls": 1000000}, CONFIG)
        self.assertIn("CFBD_STANDARD_TIER_MAPPING_UNKNOWN", private["blockers"])
        self.assertEqual(private["status"], "BLOCKED_PROVIDER_PREFLIGHT")

    def test_mapping_inconsistency_fails_closed(self):
        private, _ = evaluate_account({"patronLevel": 1, "remainingCalls": 5001}, CONFIG)
        self.assertIn("CFBD_TIER_QUOTA_MAPPING_INCONSISTENT", private["blockers"])

    def test_fetch_uses_bearer_and_info_only(self):
        seen = {}
        def opener(request, timeout=0):
            seen["url"] = request.full_url
            seen["authorization"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return _Response({"patronLevel": 1, "remainingCalls": 4000})
        out = fetch_account_info("secret-key", opener=opener)
        self.assertEqual(out["patronLevel"], 1)
        self.assertEqual(seen["url"], "https://api.collegefootballdata.com/info")
        self.assertEqual(seen["authorization"], "Bearer secret-key")
        self.assertEqual(seen["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
