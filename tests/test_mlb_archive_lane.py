from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / ".github/workflows/archive-mlb-game-odds.yml"
FAILOVER = ROOT / ".github/workflows/archive-mlb-game-odds-failover.yml"
BACKUP = ROOT / ".github/workflows/archive-mlb-game-odds-backup-dispatch.yml"
AUTO = ROOT / ".github/workflows/auto-mlb.yml"

ARCHIVE_CRON = "cron: '2,22,42 13-23,0-3 * 3-11 *'"
AUTO_CRON = "cron: '12 17,22 * 3-11 *'"


class MLBArchiveLaneContractTests(unittest.TestCase):
    def test_archive_lane_self_test_reproduces_missing_raw_regression(self):
        result = subprocess.run(
            [sys.executable, "-I", "scripts/run_mlb_archive_lane.py", "--self-test"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('"required_persistence_without_raw": "PASS"', result.stdout)
        self.assertIn('"optional_raw_persistence": "PASS"', result.stdout)
        self.assertIn('"capture_failure_heartbeat": "PASS"', result.stdout)
        self.assertIn('"capture_status_preserved": "PASS"', result.stdout)
        self.assertIn('"success_without_status_fails_closed": "PASS"', result.stdout)

    def test_only_primary_archive_wrapper_is_scheduled(self):
        primary = PRIMARY.read_text()
        self.assertIn("schedule:", primary)
        self.assertIn(ARCHIVE_CRON, primary)
        self.assertNotIn("workflow_run:", primary)

        for path in (FAILOVER, BACKUP):
            text = path.read_text()
            self.assertNotIn("schedule:", text, path.name)
            self.assertNotIn("workflow_run:", text, path.name)

    def test_archive_schedule_offsets_cover_five_minute_first_pitch_grid(self):
        offsets = (2, 22, 42)
        for minute in range(0, 60, 5):
            distances = []
            for offset in offsets:
                raw = abs(minute - offset)
                distances.append(min(raw, 60 - raw))
            self.assertLessEqual(
                min(distances),
                8,
                f"minute={minute} is outside the +/-8 minute capture window",
            )

    def test_archive_primary_and_failover_share_one_serialized_lane(self):
        for path in (PRIMARY, FAILOVER):
            text = path.read_text()
            self.assertIn("scripts/run_mlb_archive_lane.py", text, path.name)
            self.assertIn("group: archive-mlb-game-odds", text, path.name)
            self.assertIn("cancel-in-progress: false", text, path.name)
            self.assertNotIn(
                "git add runtime/odds-budget/ledger.json runtime/archive-status archive/raw_odds || true",
                text,
            )

    def test_heavy_auto_is_decoupled_and_sparse(self):
        text = AUTO.read_text()
        self.assertIn(AUTO_CRON, text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("group: auto-mlb", text)
        self.assertIn("cancel-in-progress: true", text)
        self.assertNotIn("scripts/run_mlb_archive_lane.py", text)
        self.assertNotIn("SPORTSEDGE_ARCHIVE_SOURCE", text)
        self.assertNotIn("mlb-raw-game-odds-auto-", text)
        self.assertNotIn("Propagate archive lane failure", text)

    def test_scheduler_budget_separates_light_archive_from_heavy_auto(self):
        # Start-count bound, not a claim that every job bills exactly one minute.
        # The point of the contract is that expensive full-card AUTO no longer
        # runs at archive frequency.
        archive_starts_max_31d = 15 * 3 * 31
        heavy_auto_starts_max_31d = 2 * 31
        self.assertEqual(archive_starts_max_31d, 1395)
        self.assertEqual(heavy_auto_starts_max_31d, 62)
        self.assertEqual(archive_starts_max_31d + heavy_auto_starts_max_31d, 1457)
        self.assertLess(heavy_auto_starts_max_31d, archive_starts_max_31d // 10)


if __name__ == "__main__":
    unittest.main()
