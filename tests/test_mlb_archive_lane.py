from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / ".github/workflows/archive-mlb-game-odds.yml"
FAILOVER = ROOT / ".github/workflows/archive-mlb-game-odds-failover.yml"
BACKUP = ROOT / ".github/workflows/archive-mlb-game-odds-backup-dispatch.yml"
AUTO = ROOT / ".github/workflows/auto-mlb.yml"


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

    def test_dense_archive_schedulers_are_retired(self):
        for path in (PRIMARY, FAILOVER, BACKUP):
            text = path.read_text()
            self.assertNotIn("schedule:", text, path.name)
            self.assertNotIn("workflow_run:", text, path.name)

    def test_archive_rides_existing_auto_mlb_schedule(self):
        text = AUTO.read_text()
        self.assertIn("cron: '7,22,37,52 * * * *'", text)
        self.assertIn("contents: write", text)
        self.assertIn("scripts/run_mlb_archive_lane.py", text)
        self.assertIn("Propagate archive lane failure after card evidence", text)
        self.assertIn("group: auto-mlb", text)
        self.assertIn("cancel-in-progress: false", text)

    def test_manual_archive_wrappers_use_same_canonical_lane(self):
        for path in (PRIMARY, FAILOVER):
            text = path.read_text()
            self.assertIn("scripts/run_mlb_archive_lane.py", text, path.name)
            self.assertIn("group: auto-mlb", text, path.name)
            self.assertIn("cancel-in-progress: false", text, path.name)
            self.assertNotIn(
                "git add runtime/odds-budget/ledger.json runtime/archive-status archive/raw_odds || true",
                text,
            )


if __name__ == "__main__":
    unittest.main()
