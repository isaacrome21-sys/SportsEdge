import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "active_window_guard_mlb", ROOT / "scripts" / "check_active_evidence_windows.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class MLBMoneylineActiveLivenessTests(unittest.TestCase):
    def _schedule(self, root: Path, start: str = "2026-09-17T02:00:00Z") -> Path:
        path = root / "mlb-schedule.json"
        path.write_text(json.dumps({
            "dates": [{
                "date": "2026-09-17",
                "games": [{
                    "gamePk": 123456,
                    "gameDate": start,
                    "status": {"detailedState": "Scheduled"},
                }],
            }]
        }), encoding="utf-8")
        return path

    def _decision(self, root: Path, *, status: str = "PAPER_PASS_FROZEN",
                  frozen: str = "2026-09-17T01:28:00+00:00") -> Path:
        decision_root = root / "data/mlb_forward_decisions"
        day = decision_root / "2026-09-17"
        day.mkdir(parents=True)
        row = {
            "status": status,
            "state": "PAPER",
            "stake_units": 0.0,
            "promotion_authority": False,
            "game_pk": 123456,
            "lane_id": "MLB_MONEYLINE_DK_T30_V1",
            "lane_definition_sha256": "a" * 64,
            "market_definition_sha256": "b" * 64,
            "policy_sha256": "c" * 64,
            "policy_manifest_sha256": "d" * 64,
            "edge_floor_config_sha256": "e" * 64,
            "model_artifact_sha256": "f" * 64,
            "prediction_record_sha256": "1" * 64,
            "event_start_ts": "2026-09-17T02:00:00+00:00",
            "decision_frozen_at_utc": frozen,
            "decision_quote_observed_at_utc": "2026-09-17T01:27:00+00:00",
            "graded_bet": status == "PAPER_BET_FROZEN",
            "evidence_counts": status == "PAPER_BET_FROZEN",
        }
        (day / "game_123456.json").write_text(json.dumps(row), encoding="utf-8")
        return decision_root

    def test_valid_paper_pass_is_operational_accrual(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                self._decision(root),
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(failures, [])

    def test_valid_paper_bet_is_operational_accrual(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                self._decision(root, status="PAPER_BET_FROZEN"),
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(failures, [])

    def test_missed_decision_terminal_is_fail_closed_nonaccrual(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                self._decision(root, status="BLOCKED_MISSED_DECISION_FREEZE"),
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(
                failures,
                ["MLB_MONEYLINE_ACTIVE_WINDOW_NONACCRUAL:game=123456:terminal=BLOCKED_MISSED_DECISION_FREEZE"],
            )

    def test_elapsed_due_window_without_durable_terminal_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decision_root = root / "data/mlb_forward_decisions"
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                decision_root,
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(
                failures,
                ["MLB_MONEYLINE_ACTIVE_WINDOW_ZERO_VALID_TERMINAL:game=123456"],
            )

    def test_invalid_t30_chronology_does_not_satisfy_liveness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                self._decision(root, frozen="2026-09-17T01:31:00+00:00"),
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(
                failures,
                ["MLB_MONEYLINE_ACTIVE_WINDOW_ZERO_VALID_TERMINAL:game=123456"],
            )

    def test_old_window_exits_operational_lookback_without_reclassification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            failures = MOD.mlb_moneyline_liveness_failures(
                self._schedule(root),
                root / "data/mlb_forward_decisions",
                MOD._aware("2026-09-17T08:00:00Z"),
                4.0,
            )
            self.assertEqual(failures, [])

    def test_postponed_game_is_not_a_false_due_obligation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            schedule = root / "mlb-schedule.json"
            schedule.write_text(json.dumps({
                "dates": [{"games": [{
                    "gamePk": 123456,
                    "gameDate": "2026-09-17T02:00:00Z",
                    "status": {"detailedState": "Postponed"},
                }]}]
            }), encoding="utf-8")
            failures = MOD.mlb_moneyline_liveness_failures(
                schedule,
                root / "data/mlb_forward_decisions",
                MOD._aware("2026-09-17T01:35:00Z"),
                4.0,
            )
            self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
