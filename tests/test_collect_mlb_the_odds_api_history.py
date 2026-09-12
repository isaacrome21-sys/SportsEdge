import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.collect_mlb_the_odds_api_history import (
    _canonical_request_ts,
    _provider_error_code,
    _validate_payload,
    collect_one,
)


class MLBTheOddsAPICollectorTests(unittest.TestCase):
    def test_timestamp_is_canonical_utc(self):
        self.assertEqual(_canonical_request_ts("2026-06-05T17:35:00-05:00"), "2026-06-05T22:35:00Z")

    def test_provider_snapshot_must_be_at_or_before_request(self):
        good = json.dumps({"timestamp": "2026-06-05T22:30:00Z", "data": []}).encode()
        self.assertEqual(_validate_payload(good, "2026-06-05T22:35:00Z")["timestamp"], "2026-06-05T22:30:00Z")
        bad = json.dumps({"timestamp": "2026-06-05T22:40:00Z", "data": []}).encode()
        with self.assertRaisesRegex(ValueError, "PROVIDER_TIMESTAMP_AFTER_REQUEST"):
            _validate_payload(bad, "2026-06-05T22:35:00Z")

    def test_provider_error_code_is_extracted_without_body_retention(self):
        self.assertEqual(
            _provider_error_code(b'{"error_code":"OUT_OF_USAGE_CREDITS","message":"do not persist me"}'),
            "OUT_OF_USAGE_CREDITS",
        )
        self.assertIsNone(_provider_error_code(b"not-json"))

    def test_missing_secret_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
            self.assertEqual(out["status"], "BLOCKED_NO_THE_ODDS_API_KEY")
            self.assertFalse(any(Path(td).rglob("*")))

    def test_all_out_of_credit_keys_are_classified_separately_from_auth(self):
        def exhausted(*args, **kwargs):
            body = io.BytesIO(b'{"error_code":"OUT_OF_USAGE_CREDITS","message":"quota exhausted"}')
            raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, body)

        env = {
            "SPORTSEDGE_ODDS_API_KEY": "secret-1",
            "SPORTSEDGE_ODDS_API_KEY_2": "secret-2",
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, env, clear=True):
            with patch("scripts.collect_mlb_the_odds_api_history._request", side_effect=exhausted):
                out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
        self.assertEqual(out["status"], "BLOCKED_PROVIDER_CREDITS")
        self.assertEqual(out["provider_codes"], ["OUT_OF_USAGE_CREDITS"])
        self.assertEqual([a["provider_code"] for a in out["attempts"]], ["OUT_OF_USAGE_CREDITS"] * 2)
        self.assertFalse(any(Path(td).rglob("snapshot.json")))

    def test_historical_unavailable_free_plan_is_classified_separately_from_auth(self):
        def plan_blocked(*args, **kwargs):
            body = io.BytesIO(b'{"error_code":"HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"}')
            raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, body)

        env = {
            "SPORTSEDGE_ODDS_API_KEY": "secret-1",
            "SPORTSEDGE_ODDS_API_KEY_2": "secret-2",
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, env, clear=True):
            with patch("scripts.collect_mlb_the_odds_api_history._request", side_effect=plan_blocked):
                out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
        self.assertEqual(out["status"], "BLOCKED_PROVIDER_PLAN")
        self.assertEqual(out["provider_codes"], ["HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"])
        self.assertEqual(
            [a["provider_code"] for a in out["attempts"]],
            ["HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"] * 2,
        )
        self.assertFalse(any(Path(td).rglob("snapshot.json")))

    def test_unknown_401_remains_auth_blocker(self):
        def unauthorized(*args, **kwargs):
            body = io.BytesIO(b'{"error_code":"INVALID_KEY"}')
            raise HTTPError("https://example.invalid", 401, "Unauthorized", {}, body)

        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=True
        ):
            with patch("scripts.collect_mlb_the_odds_api_history._request", side_effect=unauthorized):
                out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
        self.assertEqual(out["status"], "BLOCKED_PROVIDER_AUTH")
        self.assertEqual(out["provider_codes"], ["INVALID_KEY"])

    def test_exact_raw_bytes_and_metadata_are_archived(self):
        raw = json.dumps({
            "timestamp": "2026-06-05T22:30:00Z",
            "previous_timestamp": "2026-06-05T22:25:00Z",
            "next_timestamp": "2026-06-05T22:35:00Z",
            "data": [{"id": "event-1", "commence_time": "2026-06-05T23:10:00Z", "bookmakers": []}],
        }, separators=(",", ":")).encode()
        headers = {"x-requests-remaining": "990", "x-requests-used": "10"}
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=True):
            with patch("scripts.collect_mlb_the_odds_api_history._request", return_value=(raw, headers)):
                out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
            self.assertEqual(out["status"], "ARCHIVED_EXACT_PROVIDER_SNAPSHOT")
            raw_files = list(Path(td).rglob("snapshot.json"))
            self.assertEqual(len(raw_files), 1)
            self.assertEqual(raw_files[0].read_bytes(), raw)
            meta = json.loads(raw_files[0].with_name("snapshot.meta.json").read_text())
            self.assertEqual(meta["provider_timestamp"], "2026-06-05T22:30:00Z")
            self.assertFalse(meta["interpolated"])
            self.assertFalse(meta["reconstructed"])
            self.assertFalse(meta["promotion_authority"])
            self.assertNotIn("secret", raw_files[0].with_name("snapshot.meta.json").read_text())

    def test_existing_snapshot_is_hash_checked_and_never_overwritten(self):
        raw = json.dumps({"timestamp": "2026-06-05T22:30:00Z", "data": []}).encode()
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=True):
            with patch("scripts.collect_mlb_the_odds_api_history._request", return_value=(raw, {})):
                first = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
            self.assertEqual(first["status"], "ARCHIVED_EXACT_PROVIDER_SNAPSHOT")
            with patch("scripts.collect_mlb_the_odds_api_history._request") as request:
                second = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
            self.assertEqual(second["status"], "ALREADY_ARCHIVED")
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
