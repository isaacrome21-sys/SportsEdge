import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_mlb_the_odds_api_history import (
    _canonical_request_ts,
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

    def test_missing_secret_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {}, clear=True):
            out = collect_one(requested_at="2026-06-05T22:35:00Z", root=Path(td))
            self.assertEqual(out["status"], "BLOCKED_NO_THE_ODDS_API_KEY")
            self.assertFalse(any(Path(td).rglob("*")))

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
