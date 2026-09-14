import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.audit_nfl_2026_capture_gaps import audit, verify_due


class CaptureGapAuditTest(unittest.TestCase):
    def cfg(self, root):
        return {
            "timezone": "America/Chicago",
            "opener_weekday": "Tuesday",
            "opener_local_time": "09:00",
            "opener_window_minutes": 60,
            "week1_tuesday_local_date": "2026-09-01",
            "first_week": 2,
            "final_minutes_before_kickoff": 30,
            "final_window_minutes": 15,
            "bookmaker": "draftkings",
            "output_dir": str(Path(root) / "captures"),
        }

    def test_elapsed_missing_opener_writes_marker_not_capture(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            now = datetime(2026, 9, 12, 23, 0, tzinfo=ZoneInfo("America/Chicago"))
            written = audit(cfg, now)
            self.assertEqual(len(written), 1)
            marker = Path(root) / "captures/week02/opener_missed.json"
            opener = Path(root) / "captures/week02/opener.json"
            self.assertTrue(marker.is_file())
            self.assertFalse(opener.exists())
            data = json.loads(marker.read_text())
            self.assertEqual(data["status"], "MISSED_OR_BLOCKED")
            self.assertTrue(data["no_backfill"])
            self.assertEqual(data["reason"], "OPENER_WINDOW_ELAPSED_WITHOUT_CAPTURE")

    def test_existing_capture_prevents_marker(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            opener = Path(root) / "captures/week02/opener.json"
            opener.parent.mkdir(parents=True)
            opener.write_text("{}\n")
            now = datetime(2026, 9, 12, 23, 0, tzinfo=ZoneInfo("America/Chicago"))
            self.assertEqual(audit(cfg, now), [])
            self.assertFalse((opener.parent / "opener_missed.json").exists())

    def test_open_window_never_marks_missed(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            now = datetime(2026, 9, 8, 9, 30, tzinfo=ZoneInfo("America/Chicago"))
            self.assertEqual(audit(cfg, now), [])

    def test_marker_is_immutable(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            now = datetime(2026, 9, 12, 23, 0, tzinfo=ZoneInfo("America/Chicago"))
            audit(cfg, now)
            marker = Path(root) / "captures/week02/opener_missed.json"
            before = marker.read_bytes()
            later = datetime(2026, 9, 13, 1, 0, tzinfo=ZoneInfo("America/Chicago"))
            self.assertEqual(audit(cfg, later), [])
            self.assertEqual(marker.read_bytes(), before)

    def test_elapsed_final_group_writes_missing_count_marker(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            rows = [
                {"season": "2026", "gameday": "2026-09-10", "gametime": "20:15"},
                {"season": "2026", "gameday": "2026-09-10", "gametime": "20:15"},
            ]
            now = datetime(2026, 9, 10, 20, 5, tzinfo=ZoneInfo("America/New_York"))
            written = audit(cfg, now, rows, "abc123")
            final_markers = [p for p in written if "final_missed" in str(p)]
            self.assertEqual(len(final_markers), 1)
            data = json.loads(final_markers[0].read_text())
            self.assertEqual(data["capture_kind"], "FINAL")
            self.assertEqual(data["expected_games_at_kickoff"], 2)
            self.assertEqual(data["captured_games_at_kickoff"], 0)
            self.assertEqual(data["missing_games_at_kickoff"], 2)
            self.assertEqual(data["schedule_sha256"], "abc123")
            self.assertTrue(data["no_backfill"])

    def test_final_group_does_not_mark_before_window_ends(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            rows = [{"season": "2026", "gameday": "2026-09-10", "gametime": "20:15"}]
            now = datetime(2026, 9, 10, 19, 50, tzinfo=ZoneInfo("America/New_York"))
            written = audit(cfg, now, rows, "abc123")
            self.assertFalse(any("final_missed" in str(p) for p in written))

    def test_verify_due_opener_requires_current_run_and_contract_fields(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            opener = Path(root) / "captures/week02/opener.json"
            opener.parent.mkdir(parents=True)
            opener.write_text(json.dumps({
                "capture_kind": "OPENER",
                "book": "draftkings",
                "retrieved_at_utc": "2026-09-08T14:03:00+00:00",
                "hashes": {"policy_sha256": "x"},
                "run": {"github_run_id": "123"},
                "games": [{"commence_time": "2026-09-13T17:00:00Z"}],
            }))
            self.assertEqual(verify_due(cfg, 2, [], "123"), [])
            failures = verify_due(cfg, 2, [], "999")
            self.assertIn("DUE_OPENER_NOT_FROM_CURRENT_RUN:123", failures)

    def test_verify_due_missing_opener_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            failures = verify_due(cfg, 2, [], "123")
            self.assertTrue(any(x.startswith("DUE_OPENER_NOT_MATERIALIZED:") for x in failures))

    def test_verify_due_partial_opener_with_no_games_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            opener = Path(root) / "captures/week02/opener.json"
            opener.parent.mkdir(parents=True)
            opener.write_text(json.dumps({
                "capture_kind": "OPENER",
                "book": "draftkings",
                "retrieved_at_utc": "2026-09-08T14:03:00+00:00",
                "hashes": {"policy_sha256": "x"},
                "run": {"github_run_id": "123"},
                "games": [],
            }))
            failures = verify_due(cfg, 2, [], "123")
            self.assertIn("DUE_OPENER_EMPTY_OR_MISSING_GAMES", failures)

    def test_verify_due_final_uses_kickoff_multiplicity_and_current_run(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            final = Path(root) / "captures/week02/final/20260911T000000Z.json"
            final.parent.mkdir(parents=True)
            final.write_text(json.dumps({
                "capture_kind": "FINAL",
                "book": "draftkings",
                "retrieved_at_utc": "2026-09-11T00:00:00+00:00",
                "hashes": {"policy_sha256": "x"},
                "run": {"github_run_id": "123"},
                "games": [
                    {"commence_time": "2026-09-11T00:15:00Z"},
                    {"commence_time": "2026-09-11T00:15:00Z"},
                ],
            }))
            due = ["2026-09-11T00:15:00Z", "2026-09-11T00:15:00Z"]
            self.assertEqual(verify_due(cfg, None, due, "123"), [])
            failures = verify_due(cfg, None, due + ["2026-09-11T00:15:00Z"], "123")
            self.assertTrue(any(x.startswith("DUE_FINAL_NOT_MATERIALIZED") for x in failures))

    def test_verify_due_partial_final_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = self.cfg(root)
            final = Path(root) / "captures/week02/final/20260911T000000Z.json"
            final.parent.mkdir(parents=True)
            final.write_text(json.dumps({
                "capture_kind": "FINAL",
                "book": "draftkings",
                "retrieved_at_utc": "2026-09-11T00:00:00+00:00",
                "hashes": {"policy_sha256": "x"},
                "run": {"github_run_id": "123"},
                "games": [],
            }))
            due = ["2026-09-11T00:15:00Z"]
            failures = verify_due(cfg, None, due, "123")
            self.assertTrue(any(x.startswith("DUE_FINAL_NOT_MATERIALIZED") for x in failures))
            self.assertTrue(any(x.startswith("DUE_FINAL_EMPTY_OR_MISSING_GAMES:") for x in failures))


if __name__ == "__main__":
    unittest.main()