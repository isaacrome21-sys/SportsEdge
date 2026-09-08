import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_daily_digest import _cron_matches, _expected_runs, _capture_count


class DailyDigestTests(unittest.TestCase):
    def test_cron_match_supports_current_schedule_shapes(self):
        dt = datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
        self.assertTrue(_cron_matches("*/15 15-23,0-5 * * *", dt))
        self.assertFalse(_cron_matches("7,22,37,52 * * * *", dt))

    def test_expected_runs_distinguishes_no_schedule(self):
        with TemporaryDirectory() as td:
            p = Path(td) / "wf.yml"
            p.write_text("name: x\non:\n  workflow_dispatch:\n", encoding="utf-8")
            now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
            self.assertIsNone(_expected_runs(p, now, now))

    def test_capture_count_reports_no_data_not_zero(self):
        self.assertEqual(_capture_count([], "archive-status"), "NO DATA")
        self.assertEqual(_capture_count([], None), "NO DATA")


if __name__ == "__main__":
    unittest.main()
