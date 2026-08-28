from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from sportsedge.mlb_pit_watch import (
    MLBPITWatchError,
    next_capture_time,
    publish_data_branch,
    run_pit_iteration,
)


class PITWatchTests(unittest.TestCase):
    def test_cadence_matches_archive_scheduler(self):
        for minute, second, expected, hour_delta in (
            (0, 30, 7, 0), (7, 0, 22, 0), (7, 1, 22, 0),
            (52, 30, 7, 1), (59, 59, 7, 1),
        ):
            now = datetime(2026, 8, 26, 13, minute, second, tzinfo=timezone.utc)
            nxt = next_capture_time(now)
            self.assertGreater(nxt, now)
            self.assertEqual(nxt.minute, expected)
            self.assertEqual(nxt.hour, (13 + hour_delta) % 24)

    def test_additional_failure_does_not_destroy_prop_capture(self):
        def boom(_):
            raise RuntimeError("odds down")
        out = run_pit_iteration(
            now=datetime(2026, 8, 26, 13, tzinfo=timezone.utc),
            capture_props=lambda _: {"pit_target_quote_count": 5},
            capture_additional=boom,
        )
        self.assertEqual(out.prop_status, "CAPTURED")
        self.assertEqual(out.prop_count, 5)
        self.assertEqual(out.additional_status, "ERROR")
        self.assertTrue(any(x.startswith("ADDITIONAL:RuntimeError") for x in out.failures))

    def test_outside_t90_is_legitimate_skip(self):
        out = run_pit_iteration(
            now=datetime(2026, 8, 26, 13, tzinfo=timezone.utc),
            capture_props=lambda _: {"pit_target_quote_count": 1},
            capture_additional=lambda _: {
                "capture_status": "SKIP_OUTSIDE_CAPTURE_WINDOW",
                "pit_quote_count": 0,
            },
        )
        self.assertEqual(out.additional_status, "SKIP_OUTSIDE_CAPTURE_WINDOW")
        self.assertEqual(out.failures, ())

    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(MLBPITWatchError, "TIMEZONE_REQUIRED"):
            next_capture_time(datetime(2026, 8, 26))

    def test_publish_real_git_data_branch_and_repeat_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            bare = base / "remote.git"
            root = base / "repo"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "init", str(root)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
            (root / "README").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "branch", "-M", "main"], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(bare)], check=True)
            subprocess.run(["git", "-C", str(root), "push", "-u", "origin", "main"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "-C", str(root), "branch", "data"], check=True)
            subprocess.run(["git", "-C", str(root), "push", "origin", "data"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            prop = root / "artifacts" / "prop_odds" / "2026-08-26"
            additional = root / "artifacts" / "additional_odds" / "2026-08-26"
            prop.mkdir(parents=True); additional.mkdir(parents=True)
            (prop / "props.json").write_text("{}", encoding="utf-8")
            (additional / "additional.json").write_text("{}", encoding="utf-8")

            self.assertTrue(publish_data_branch(root))
            self.assertFalse(publish_data_branch(root))

            verify = base / "verify"
            subprocess.run(["git", "clone", "--branch", "data", str(bare), str(verify)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertTrue((verify / "runtime/mlb-prop-pit/2026-08-26/props.json").exists())
            self.assertTrue((verify / "runtime/mlb-additional-pit/2026-08-26/additional.json").exists())


if __name__ == "__main__":
    unittest.main()
