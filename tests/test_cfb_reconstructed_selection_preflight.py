from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.preflight_cfb_reconstructed_selection import evaluate_account, fetch_account_info


ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "standard_tier_monthly_quotas": {"0": 1000, "1": 5000, "2": 30000, "3": 75000, "4": 125000, "5": 200000, "6": 500000},
    "tier_labels": {"0": "FREE", "1": "TIER_1", "2": "TIER_2", "3": "TIER_3", "4": "TIER_4", "5": "TIER_5", "6": "TIER_6"},
    "planned_new_calls_upper_bound": {"total": 244},
    "retry_reserve_calls": 50,
    "weather_reconstruction": {
        "contract": "CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE",
        "venue_endpoint": "/venues",
        "archive_endpoint": "https://archive-api.open-meteo.com/v1/archive",
        "archive_model": "era5",
        "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "promotion_authority": False,
    },
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
        self.assertTrue(public["weather_transport_ready"])
        self.assertFalse(public["cfbd_weather_required_for_selection"])
        self.assertEqual(private["historical_replay_calls_performed"], 0)
        self.assertTrue(all(value is False for value in private["authority"].values()))

    def test_free_tier_is_not_blocked_by_paid_weather_entitlement(self):
        private, public = evaluate_account({"patronLevel": 0, "remainingCalls": 900}, CONFIG)
        self.assertEqual(private["status"], "VERIFIED_BEFORE_FIRST_REPLAY_CALL")
        self.assertFalse(public["cfbd_weather_entitled"])
        self.assertFalse(public["cfbd_weather_required_for_selection"])
        self.assertTrue(public["weather_transport_ready"])
        self.assertEqual(private["historical_replay_calls_performed"], 0)

    def test_remaining_quota_must_cover_plan_and_retry_reserve(self):
        private, _ = evaluate_account({"patronLevel": 1, "remainingCalls": 293}, CONFIG)
        self.assertIn("CFBD_REPLAY_PLAN_EXCEEDS_REMAINING_QUOTA", private["blockers"])
        self.assertEqual(private["status"], "BLOCKED_PROVIDER_PREFLIGHT")

    def test_exact_plan_plus_reserve_is_admissible(self):
        private, _ = evaluate_account({"patronLevel": 1, "remainingCalls": 294}, CONFIG)
        self.assertEqual(private["status"], "VERIFIED_BEFORE_FIRST_REPLAY_CALL")

    def test_invalid_weather_transport_fails_closed(self):
        bad = {**CONFIG, "weather_reconstruction": {**CONFIG["weather_reconstruction"], "archive_model": "best_match"}}
        private, public = evaluate_account({"patronLevel": 1, "remainingCalls": 4700}, bad)
        self.assertEqual(private["status"], "BLOCKED_PROVIDER_PREFLIGHT")
        self.assertIn("CFB_RECONSTRUCTED_WEATHER_TRANSPORT_CONTRACT_INVALID", private["blockers"])
        self.assertFalse(public["weather_transport_ready"])

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

    def test_hosted_preflight_asserts_reconstructed_weather_transport_not_paid_weather(self):
        text = (ROOT / ".github/workflows/cfb-reconstructed-selection-provider-preflight.yml").read_text()
        self.assertIn("report.get('weather_transport_ready') is not True", text)
        self.assertIn("report.get('cfbd_weather_required_for_selection') is not False", text)
        self.assertIn("CFBD_VENUES_OPEN_METEO_ERA5_RECONSTRUCTED_CURRENT_PROVIDER_VINTAGE", text)
        self.assertNotIn("report.get('weather_entitled')", text)
        self.assertNotIn("CFB_PREFLIGHT_WEATHER_NOT_ENTITLED", text)


if __name__ == "__main__":
    unittest.main()
