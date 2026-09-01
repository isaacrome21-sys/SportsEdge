import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.check_mlb_auto_heartbeat import evaluate_runs, fetch_auto_mlb_runs


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def run(*, minutes_ago=10, conclusion="success", status="completed", run_id=1, stamp=True):
    row = {"id": run_id, "status": status, "conclusion": conclusion}
    if stamp:
        dt = datetime.fromtimestamp(NOW.timestamp() - minutes_ago * 60, tz=timezone.utc)
        row["updated_at"] = dt.isoformat().replace("+00:00", "Z")
    return row


class MLBDeadmanTests(unittest.TestCase):
    def test_recent_success_is_healthy(self):
        result = evaluate_runs([run(minutes_ago=10)], now=NOW, max_age_minutes=45)
        self.assertTrue(result["healthy"])
        self.assertEqual(result["problems"], [])

    def test_stale_success_fails(self):
        result = evaluate_runs([run(minutes_ago=46)], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertTrue(any(problem.startswith("DEADMAN_STALE:") for problem in result["problems"]))

    def test_recent_failed_run_fails(self):
        result = evaluate_runs([run(minutes_ago=10, conclusion="failure")], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertIn("DEADMAN_LATEST_RUN_NOT_SUCCESSFUL:conclusion=failure", result["problems"])

    def test_stale_failed_run_reports_both_problems(self):
        result = evaluate_runs([run(minutes_ago=60, conclusion="failure")], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertEqual(len(result["problems"]), 2)

    def test_skipped_is_not_accepted_as_healthy(self):
        result = evaluate_runs([run(minutes_ago=10, conclusion="skipped")], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertIn("DEADMAN_LATEST_RUN_NOT_SUCCESSFUL:conclusion=skipped", result["problems"])

    def test_no_completed_runs_fails(self):
        result = evaluate_runs([run(status="in_progress", conclusion=None)], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["problems"], ["DEADMAN_NO_COMPLETED_AUTO_MLB_RUNS"])

    def test_missing_timestamp_fails(self):
        result = evaluate_runs([run(stamp=False)], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["problems"], ["DEADMAN_LATEST_RUN_TIMESTAMP_MISSING"])

    def test_future_timestamp_fails(self):
        result = evaluate_runs([run(minutes_ago=-10)], now=NOW, max_age_minutes=45)
        self.assertFalse(result["healthy"])
        self.assertTrue(any(problem.startswith("DEADMAN_FUTURE_HEARTBEAT:") for problem in result["problems"]))

    @patch("scripts.check_mlb_auto_heartbeat.subprocess.check_output")
    def test_fetch_pins_gh_api_to_get(self, check_output):
        check_output.return_value = json.dumps({"workflow_runs": []})
        self.assertEqual(fetch_auto_mlb_runs("owner/repo"), [])
        command = check_output.call_args.args[0]
        self.assertEqual(command[:4], ["gh", "api", "--method", "GET"])
        self.assertIn("branch=main", command)
        self.assertIn("per_page=10", command)

    @patch("scripts.check_mlb_auto_heartbeat.subprocess.check_output")
    def test_fetch_api_error_propagates_for_fail_closed_cli(self, check_output):
        check_output.side_effect = subprocess.CalledProcessError(1, ["gh", "api"])
        with self.assertRaises(subprocess.CalledProcessError):
            fetch_auto_mlb_runs("owner/repo")


if __name__ == "__main__":
    unittest.main()
