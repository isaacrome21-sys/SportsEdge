import csv
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sportsedge import nfl_confirmation_schedule as sched

UTC = timezone.utc


def base_cfg(root):
    return {
        "timezone": "America/Chicago",
        "week1_tuesday_local_date": "2026-09-08",
        "first_week": 2,
        "final_minutes_before_kickoff": 30,
        "final_window_minutes": 15,
        "bookmaker": "draftkings",
        "source_priority": ["DRAFTKINGS_DIRECT_WEB_V1", "DRAFTKINGS_ODDS_API_V1"],
        "output_dir": str(Path(root) / "captures"),
    }


def write_schedule(path):
    rows = [
        {"season": "2026", "gameday": "2026-09-24", "gametime": "20:15"},
        {"season": "2026", "gameday": "2026-09-27", "gametime": "13:00"},
        {"season": "2026", "gameday": "2026-09-27", "gametime": "13:00"},
        {"season": "2026", "gameday": "2026-09-27", "gametime": "16:25"},
        {"season": "2026", "gameday": "2026-09-28", "gametime": "20:15"},
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["season", "gameday", "gametime"])
        writer.writeheader()
        writer.writerows(rows)


class ConfirmationScheduleTests(unittest.TestCase):
    def test_opener_expected_uses_kickoff_multiplicity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "games.csv"
            write_schedule(path)
            snap = sched.load_snapshot(path)
            expected = sched.opener_expected_kickoffs(base_cfg(td), 3, snap)
            self.assertEqual(sum(expected.values()), 5)
            # Two Sunday 1pm ET games share the same kickoff and must remain count=2.
            self.assertIn(2, expected.values())

    def test_exact_coverage_rejects_partial_slate(self):
        expected = Counter({"2026-09-27T17:00:00Z": 2})
        rows = [{"commence_time": "2026-09-27T17:00:00Z"}]
        with self.assertRaisesRegex(sched.ScheduleExpectationError, "SCHEDULE_COVERAGE_MISMATCH"):
            sched.require_exact_coverage(rows, expected, kind="OPENER")

    def test_exact_coverage_accepts_same_kickoff_multiplicity(self):
        expected = Counter({"2026-09-27T17:00:00Z": 2})
        rows = [
            {"commence_time": "2026-09-27T17:00:00Z"},
            {"commence_time": "2026-09-27T17:00:00Z"},
        ]
        sched.require_exact_coverage(rows, expected, kind="OPENER")

    def test_final_due_subtracts_only_admissible_prior_capture(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "games.csv"
            # One game at 13:00 ET = 17:00Z during daylight time.
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["season", "gameday", "gametime"])
                writer.writeheader()
                writer.writerow({"season": "2026", "gameday": "2026-09-27", "gametime": "13:00"})
            cfg = base_cfg(td)
            snap = sched.load_snapshot(path)
            now = datetime(2026, 9, 27, 16, 31, tzinfo=UTC)
            due = sched.final_expected_due_kickoffs(cfg, now, snap)
            self.assertEqual(due, Counter({"2026-09-27T17:00:00Z": 1}))

            final_dir = Path(cfg["output_dir"]) / "week03" / "final"
            final_dir.mkdir(parents=True)
            record = {
                "capture_kind": "FINAL",
                "book": "draftkings",
                "source_class": "DRAFTKINGS_DIRECT_WEB_V1",
                "retrieved_at_utc": "2026-09-27T16:31:00Z",
                "hashes": {"script_sha256": "x"},
                "games": [{
                    "commence_time": "2026-09-27T17:00:00Z",
                    "spread": {"status": "OK"},
                    "total": {"status": "OK"},
                }],
            }
            (final_dir / "x.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(sched.final_expected_due_kickoffs(cfg, now, snap), Counter())

            # Malformed prior evidence must not suppress a due game.
            record["games"][0]["total"] = {"status": "ONE_SIDED"}
            (final_dir / "x.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(
                sched.final_expected_due_kickoffs(cfg, now, snap),
                Counter({"2026-09-27T17:00:00Z": 1}),
            )


if __name__ == "__main__":
    unittest.main()
