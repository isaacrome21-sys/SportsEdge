import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import nfl_2026_line_capture as cap

UTC = timezone.utc


def cfg(root):
    return {
        "opener_weekday": "Tuesday",
        "opener_local_time": "09:00",
        "opener_window_minutes": 60,
        "final_minutes_before_kickoff": 30,
        "final_window_minutes": 15,
        "timezone": "America/Chicago",
        "week1_tuesday_local_date": "2026-09-08",
        "first_week": 2,
        "sport_key": "americanfootball_nfl",
        "bookmaker": "draftkings",
        "markets": ["spreads", "totals"],
        "source_priority": [cap.DIRECT_SOURCE_CLASS, cap.API_SOURCE_CLASS],
        "fallback_scope": "WHOLE_SOURCE_FAILURE_ONLY",
        "cross_source_market_merge": False,
        "direct_valid_board_market_gaps_trigger_fallback": False,
        "output_dir": str(Path(root) / "captures"),
        "predictions_dir": str(Path(root) / "predictions"),
    }


def direct_transport(raw=b'{"provider":"exact bytes"}'):
    return {
        "source_class": cap.DIRECT_SOURCE_CLASS,
        "source_uri": "https://sportsbook-nash.draftkings.com/api/test",
        "transport_host": "sportsbook-nash.draftkings.com",
        "observed_at_utc": "2026-09-22T14:05:00Z",
        "raw_bytes": raw,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "attempts": [{"attempt": 1, "host": "sportsbook-nash.draftkings.com", "result_class": "OK"}],
        "adapter_module_sha256": "a" * 64,
    }


def ok_row():
    return {
        "event_id": "E1",
        "home_team": "Chicago Bears",
        "away_team": "Green Bay Packers",
        "commence_time": "2026-09-27T17:00:00Z",
        "week": 3,
        "book": "draftkings",
        "source_class": cap.DIRECT_SOURCE_CLASS,
        "book_last_update": None,
        "observed_at_utc": "2026-09-22T14:05:00Z",
        "spread": {"status": "OK", "market_last_update": None, "home_point": -3.5,
                   "home_price": -110, "away_point": 3.5, "away_price": -110},
        "total": {"status": "OK", "market_last_update": None, "point": 44.5,
                  "over_price": -105, "under_price": -115},
    }


class DirectCaptureWiringTests(unittest.TestCase):
    NOW = datetime(2026, 9, 22, 14, 5, tzinfo=UTC)
    HASHES = {"policy_sha256": "p", "config_sha256": "c", "script_sha256": "s"}

    def test_direct_success_is_primary_and_creates_lock_only_after_admission(self):
        with tempfile.TemporaryDirectory() as td:
            c = cfg(td)
            with patch.object(cap, "acquire_direct_rows", return_value=(direct_transport(), [ok_row()])), \
                 patch.object(cap, "api_opener_rows") as fallback:
                record = cap.do_opener(c, self.NOW, self.HASHES)
            fallback.assert_not_called()
            self.assertEqual(record["source_class"], cap.DIRECT_SOURCE_CLASS)
            self.assertEqual(record["lock_status"], "LOCK_CREATED")
            self.assertTrue((Path(c["output_dir"]) / "capture_lock.json").is_file())
            raw_path = Path(record["transport"]["raw_relative_path"])
            self.assertEqual(raw_path.read_bytes(), direct_transport()["raw_bytes"])

    def test_direct_market_gap_never_falls_through_and_never_locks(self):
        with tempfile.TemporaryDirectory() as td:
            c = cfg(td)
            bad = ok_row()
            bad["total"] = {"status": "ONE_SIDED"}
            with patch.object(cap, "acquire_direct_rows", return_value=(direct_transport(), [bad])), \
                 patch.object(cap, "api_opener_rows") as fallback:
                with self.assertRaisesRegex(cap.CaptureError, "TWO_SIDED_ADMISSION_FAILED"):
                    cap.do_opener(c, self.NOW, self.HASHES)
            fallback.assert_not_called()
            self.assertFalse((Path(c["output_dir"]) / "capture_lock.json").exists())
            self.assertFalse((Path(c["output_dir"]) / "week03" / "opener.json").exists())

    def test_only_whole_source_failure_can_reach_vendor_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            c = cfg(td)
            odds = {
                "received_at_utc": "2026-09-22T14:06:00+00:00",
                "key_slot": 2,
                "quota": {},
                "failed_key_slots": [{"key_slot": 1, "http_status": 401}],
                "raw_sha256": "b" * 64,
                "data": [],
            }
            events = {
                "received_at_utc": "2026-09-22T14:06:00+00:00",
                "key_slot": 2,
                "quota": {},
                "failed_key_slots": [{"key_slot": 1, "http_status": 401}],
                "raw_sha256": "c" * 64,
                "data": [],
            }
            vendor_row = ok_row()
            vendor_row["source_class"] = cap.API_SOURCE_CLASS
            failure = cap.DirectSourceFailure("DK_DIRECT_BOARD_UNAVAILABLE", attempts=[{"attempt": 1, "result_class": "DK_GAME_FETCH_FAILED"}])
            with patch.object(cap, "acquire_direct_rows", side_effect=failure), \
                 patch.object(cap, "api_opener_rows", return_value=(events, odds, [vendor_row])) as fallback:
                record = cap.do_opener(c, self.NOW, self.HASHES)
            fallback.assert_called_once()
            self.assertEqual(record["source_class"], cap.API_SOURCE_CLASS)
            self.assertEqual(record["transport"]["direct_attempts"], failure.attempts)

    def test_raw_hash_mismatch_cannot_create_lock(self):
        with tempfile.TemporaryDirectory() as td:
            c = cfg(td)
            t = direct_transport()
            t["raw_sha256"] = "0" * 64
            with patch.object(cap, "acquire_direct_rows", return_value=(t, [ok_row()])):
                with self.assertRaisesRegex(cap.CaptureError, "DIRECT_RAW_HASH_MISMATCH"):
                    cap.do_opener(c, self.NOW, self.HASHES)
            self.assertFalse((Path(c["output_dir"]) / "capture_lock.json").exists())


if __name__ == "__main__":
    unittest.main()
