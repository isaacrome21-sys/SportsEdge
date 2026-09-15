import csv
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "active_window_guard", ROOT / "scripts" / "check_active_evidence_windows.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class ActiveEvidenceWindowGuardTests(unittest.TestCase):
    def test_mutation_guard_accepts_intact_active_authority_and_ignores_closed_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "config").mkdir()
            (root / ".github/workflows/capture.yml").write_text(
                "schedule:\n  - cron: '0 * * * *'\nrun: capture.py\npath: durable/root\n",
                encoding="utf-8",
            )
            (root / ".github/workflows/deadman.yml").write_text(
                "workflow_run:\n  workflows: [other-writer]\nrun: python check_active_evidence_windows.py\n",
                encoding="utf-8",
            )
            registry = {
                "schema": "SPORTSEDGE_ACTIVE_EVIDENCE_WINDOWS_V1",
                "windows": [
                    {
                        "id": "ACTIVE",
                        "status": "ACTIVE",
                        "acquisition_authority": ".github/workflows/capture.yml",
                        "persistence_root": "durable/root",
                        "independent_liveness_authority": ".github/workflows/deadman.yml",
                        "required_authority_literals": ["schedule:", "capture.py"],
                        "required_liveness_literals": [
                            "workflow_run:", "other-writer", "check_active_evidence_windows.py"
                        ],
                    },
                    {
                        "id": "CLOSED",
                        "status": "CLOSED_FAILED_NONACCRUAL",
                        "acquisition_authority": ".github/workflows/does-not-exist.yml",
                    },
                ],
            }
            path = root / "config/registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(MOD.mutation_failures(root, path), [])

    def test_mutation_guard_fails_when_active_schedule_authority_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "config").mkdir()
            (root / ".github/workflows/capture.yml").write_text("run: capture.py\n", encoding="utf-8")
            registry = {
                "schema": "SPORTSEDGE_ACTIVE_EVIDENCE_WINDOWS_V1",
                "windows": [{
                    "id": "ACTIVE",
                    "status": "ACTIVE",
                    "acquisition_authority": ".github/workflows/capture.yml",
                    "required_authority_literals": ["schedule:", "capture.py"],
                }],
            }
            path = root / "config/registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            failures = MOD.mutation_failures(root, path)
            self.assertIn("ACTIVE_WINDOW_AUTHORITY_CONTRACT_MISSING:ACTIVE:schedule:", failures)

    def test_mutation_guard_fails_when_declared_liveness_trigger_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "config").mkdir()
            (root / ".github/workflows/capture.yml").write_text(
                "schedule:\nrun: capture.py\npath: durable/root\n", encoding="utf-8"
            )
            (root / ".github/workflows/deadman.yml").write_text(
                "run: python check_active_evidence_windows.py\n", encoding="utf-8"
            )
            registry = {
                "schema": "SPORTSEDGE_ACTIVE_EVIDENCE_WINDOWS_V1",
                "windows": [{
                    "id": "ACTIVE",
                    "status": "ACTIVE",
                    "acquisition_authority": ".github/workflows/capture.yml",
                    "persistence_root": "durable/root",
                    "independent_liveness_authority": ".github/workflows/deadman.yml",
                    "required_authority_literals": ["schedule:", "capture.py"],
                    "required_liveness_literals": ["workflow_run:", "check_active_evidence_windows.py"],
                }],
            }
            path = root / "config/registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            failures = MOD.mutation_failures(root, path)
            self.assertIn("ACTIVE_WINDOW_LIVENESS_CONTRACT_MISSING:ACTIVE:workflow_run:", failures)

    def _write_capture_config(self, root: Path) -> Path:
        cfg = {
            "opener_weekday": "Tuesday",
            "opener_local_time": "09:00",
            "opener_window_minutes": 60,
            "final_minutes_before_kickoff": 30,
            "final_window_minutes": 15,
            "timezone": "America/Chicago",
            "week1_tuesday_local_date": "2026-09-08",
            "first_week": 2,
            "bookmaker": "draftkings",
            "output_dir": "data/nfl_2026_confirmation/captures",
        }
        path = root / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path

    def _write_schedule(self, root: Path, rows=None) -> Path:
        path = root / "games.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["season", "gameday", "gametime"])
            writer.writeheader()
            for row in rows or []:
                writer.writerow(row)
        return path

    def test_nfl_liveness_fails_after_week2_opener_window_with_no_durable_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = self._write_capture_config(root)
            schedule = self._write_schedule(root)
            old = Path.cwd()
            os.chdir(root)
            try:
                failures = MOD.nfl_liveness_failures(
                    cfg,
                    schedule,
                    MOD._aware("2026-09-15T15:17:00Z"),
                    4.0,
                )
            finally:
                os.chdir(old)
            self.assertIn("NFL_ACTIVE_WINDOW_ZERO_VALID_OPENER:week=2:NO_TERMINAL_RECORD", failures)

    def test_nfl_liveness_accepts_contract_valid_week2_opener(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = self._write_capture_config(root)
            schedule = self._write_schedule(root)
            opener = root / "data/nfl_2026_confirmation/captures/week02/opener.json"
            opener.parent.mkdir(parents=True)
            opener.write_text(json.dumps({
                "capture_kind": "OPENER",
                "book": "draftkings",
                "retrieved_at_utc": "2026-09-15T14:05:00Z",
                "hashes": {"raw": "abc"},
                "games": [{"commence_time": "2026-09-17T00:00:00Z"}],
            }), encoding="utf-8")
            old = Path.cwd()
            os.chdir(root)
            try:
                failures = MOD.nfl_liveness_failures(
                    cfg,
                    schedule,
                    MOD._aware("2026-09-15T15:17:00Z"),
                    4.0,
                )
            finally:
                os.chdir(old)
            self.assertEqual(failures, [])

    def test_nfl_liveness_fails_after_recent_final_window_without_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = self._write_capture_config(root)
            schedule = self._write_schedule(root, [{
                "season": "2026",
                "gameday": "2026-09-17",
                "gametime": "20:20",
            }])
            old = Path.cwd()
            os.chdir(root)
            try:
                failures = MOD.nfl_liveness_failures(
                    cfg,
                    schedule,
                    MOD._aware("2026-09-18T00:10:00Z"),
                    4.0,
                )
            finally:
                os.chdir(old)
            self.assertTrue(any(item.startswith("NFL_ACTIVE_WINDOW_ZERO_OR_INCOMPLETE_FINAL:") for item in failures))


if __name__ == "__main__":
    unittest.main()
