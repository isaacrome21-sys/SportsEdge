import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.build_daily_digest_v2 import (
    LANES,
    _capture_count,
    _cron_matches,
    _durable_credit_sum,
    _expected_runs,
    _lane_health,
    build_digest,
)

UTC = timezone.utc


class DailyDigestTests(unittest.TestCase):
    def test_cron_match_supports_current_schedule_shapes(self):
        dt = datetime(2026, 9, 8, 15, 30, tzinfo=UTC)
        self.assertTrue(_cron_matches("*/15 15-23,0-5 * * *", dt))
        self.assertFalse(_cron_matches("7,22,37,52 * * * *", dt))

    def test_expected_runs_distinguishes_no_schedule(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "wf.yml"
            path.write_text("name: x\non:\n  workflow_dispatch:\n", encoding="utf-8")
            now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
            self.assertIsNone(_expected_runs(path, now, now))

    def test_capture_count_reports_no_data_not_zero(self):
        self.assertEqual(_capture_count([], "archive-status"), "NO DATA")
        self.assertEqual(_capture_count([], None), "NOT CONFIGURED")

    def test_null_credits_are_unknown_never_zero(self):
        now = datetime(2026, 9, 8, 13, 0, tzinfo=UTC)
        rows = [
            (
                Path("runtime/archive-status/2026-09-08/run.json"),
                {"run_at_utc": now.isoformat(), "credits_consumed_actual": None},
            )
        ]
        value, state = _durable_credit_sum(
            rows,
            cutoff=now - timedelta(hours=1),
            now=now,
        )
        self.assertIsNone(value)
        self.assertIn("UNKNOWN", state)

    def test_single_lane_zero_is_failure(self):
        runs = [{"conclusion": "failure"}]
        health = _lane_health(
            expected=4,
            lane_runs=runs,
            durable="NO DATA",
            durable_required=True,
        )
        self.assertEqual(health["state"], "FAILURE — 0% SUCCESS")
        self.assertEqual(health["passed"], 0)

    def test_mixed_partial_is_degraded_not_pass(self):
        runs = [{"conclusion": "success"}, {"conclusion": "failure"}]
        health = _lane_health(
            expected=2,
            lane_runs=runs,
            durable="1 durable CAPTURED records",
            durable_required=True,
        )
        self.assertEqual(health["state"], "DEGRADED — PARTIAL SUCCESS")
        self.assertEqual(health["passed"], 1)

    def test_genuinely_nothing_scheduled_is_no_data(self):
        health = _lane_health(
            expected=None,
            lane_runs=[],
            durable="NO DATA",
            durable_required=True,
        )
        self.assertEqual(health["state"], "NO DATA — NOTHING SCHEDULED")

    def _write_workflows(self, root: Path, *, scheduled: bool = True):
        wf_root = root / ".github" / "workflows"
        wf_root.mkdir(parents=True, exist_ok=True)
        for _, _, workflow, _ in LANES:
            cron = "  schedule:\n    - cron: '0 * * * *'\n" if scheduled else ""
            (wf_root / workflow).write_text(
                f"name: {workflow.removesuffix('.yml')}\non:\n  workflow_dispatch:\n{cron}",
                encoding="utf-8",
            )

    def _run(self, root: Path, runs):
        now = datetime(2026, 9, 8, 13, 30, tzinfo=UTC)
        with (
            patch("scripts.build_daily_digest_v2._recent_runs", return_value=runs),
            patch("scripts.build_daily_digest_v2._failure_details", return_value={int(r["id"]): "sample error" for r in runs if r.get("conclusion") == "failure"}),
            patch("scripts.build_daily_digest_v2._data_rows_since", return_value=[]),
            patch("scripts.build_daily_digest_v2._mlb_schedule", return_value=([], None)),
            patch("scripts.build_daily_digest_v2._nfl_windows", return_value=([], None)),
            patch("scripts.build_daily_digest_v2._odds_usage", return_value=(["- test"], [])),
        ):
            return build_digest(
                repo_root=root,
                data_root=root / "data",
                token="token",
                repo="owner/repo",
                now=now,
            )

    def test_all_lanes_zero_emit_system_outage_and_needs_isaac(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_workflows(root)
            runs = []
            for index, (_, _, workflow, _) in enumerate(LANES, start=1):
                runs.append(
                    {
                        "id": 1000 + index,
                        "name": workflow.removesuffix(".yml"),
                        "event": "schedule",
                        "conclusion": "failure",
                        "created_at": "2026-09-08T13:00:00Z",
                    }
                )
            digest = self._run(root, runs)
            self.assertIn("# 🚨 SYSTEM OUTAGE", digest)
            self.assertIn("5 monitored lanes are at 0% success", digest)
            self.assertNotIn("NEEDS ISAAC\n- NONE", digest)

    def test_one_zero_lane_does_not_emit_system_outage(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_workflows(root)
            runs = []
            for index, (_, _, workflow, _) in enumerate(LANES, start=1):
                runs.append(
                    {
                        "id": 2000 + index,
                        "name": workflow.removesuffix(".yml"),
                        "event": "schedule",
                        "conclusion": "failure" if index == 1 else "success",
                        "created_at": "2026-09-08T13:00:00Z",
                    }
                )
            digest = self._run(root, runs)
            self.assertNotIn("# 🚨 SYSTEM OUTAGE", digest)
            self.assertIn("FAILURE — 0% SUCCESS", digest)
            self.assertIn("## NEEDS ISAAC", digest)

    def test_genuinely_nothing_scheduled_does_not_false_alarm(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            self._write_workflows(root, scheduled=False)
            digest = self._run(root, [])
            self.assertNotIn("# 🚨 SYSTEM OUTAGE", digest)
            self.assertIn("NO DATA — NOTHING SCHEDULED", digest)
            self.assertIn("UNKNOWN — insufficient evidence to assert NONE", digest)


if __name__ == "__main__":
    unittest.main()
