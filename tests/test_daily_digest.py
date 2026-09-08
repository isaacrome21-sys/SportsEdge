import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_daily_digest import _cron_matches, _expected_runs, _capture_count, _odds_usage


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

    def test_terminal_quota_state_dominates_stale_success_and_zero_consumption(self):
        path = Path("artifacts/archive-status/status.json")
        rows = [
            (path, {
                "run_at_utc": "2026-09-08T08:00:00+00:00",
                "status": "CAPTURED",
                "provider_state": "AVAILABLE",
                "provider_credits_used": 100,
                "credits_consumed_actual": 3,
            }),
            (path, {
                "run_at_utc": "2026-09-08T09:00:00+00:00",
                "status": "BLOCKED_NO_CREDITS",
                "reason": "ACCOUNT_LEVEL_USAGE_CREDITS_EXHAUSTED",
                "provider_state": "ACCOUNT_TERMINAL",
                "provider_error_code": "OUT_OF_USAGE_CREDITS",
                # Legacy failure rows may say zero; this must never make the
                # digest look healthy or available.
                "credits_consumed_actual": 0,
            }),
        ]
        usage, needs = _odds_usage(rows)
        self.assertTrue(usage.startswith("HARD OUTAGE"), usage)
        self.assertIn("OUT_OF_USAGE_CREDITS", usage)
        self.assertIn("last provider success=2026-09-08T08:00:00+00:00", usage)
        self.assertIn("Zero observed consumption does not imply provider availability", usage)
        self.assertIn("ACCOUNT_LEVEL_USAGE_CREDITS_EXHAUSTED", needs)


if __name__ == "__main__":
    unittest.main()
