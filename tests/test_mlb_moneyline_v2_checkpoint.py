from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
from sportsedge.mlb_moneyline_forward_lane import load_forward_lane_binding
from sportsedge.mlb_moneyline_v2_checkpoint import (
    MLBMoneylineV2CheckpointError,
    _student_t_critical_975,
)
from sportsedge.mlb_moneyline_v2_checkpoint_runtime import (
    evaluate_evidence_tree,
    evaluate_v2_checkpoints,
    main as checkpoint_runtime_main,
)


class MLBMoneylineV2CheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = load_forward_lane_binding()
        cls.artifact = mlb_model_artifact_sha256()

    def _row(
        self,
        index: int,
        *,
        slate_index: int | None = None,
        clv: float | None = 0.02,
        won: bool = True,
    ) -> dict:
        slate_index = index // 10 if slate_index is None else slate_index
        day = datetime(2026, 9, 17, tzinfo=timezone.utc) + timedelta(days=slate_index)
        start = day.replace(hour=18, minute=index % 10, second=0)
        decision = start - timedelta(minutes=35)
        close = start - timedelta(minutes=5)
        row = {
            "schema_version": "mlb_moneyline_forward_evidence_v2",
            "status": "FORWARD_EVIDENCE_COMPLETE_V2",
            "state": "PAPER",
            "graded_bet": True,
            "evidence_counts": True,
            "stake_units": 0.0,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
            "lane_id": self.binding["lane_id"],
            "lane_definition_sha256": self.binding["lane_definition_sha256"],
            "market_definition_sha256": self.binding["market_definition_sha256"],
            "policy_id": self.binding["policy_id"],
            "policy_sha256": self.binding["policy_sha256"],
            "policy_manifest_sha256": self.binding["policy_manifest_sha256"],
            "edge_floor_config_sha256": self.binding["edge_floor_config_sha256"],
            "game_pk": 900000 + index,
            "slate_date": start.date().isoformat(),
            "event_start_ts": start.isoformat(),
            "model_artifact_sha256": self.artifact,
            "selected_side": "HOME",
            "entry_selected_odds": 100.0,
            "entry_fair_probability": 0.50,
            "decision_frozen_at_utc": decision.isoformat(),
            "outcome": 1 if won else 0,
            "paper_profit_units_per_1u": 1.0 if won else -1.0,
            "paper_roi_fraction_per_1u": 1.0 if won else -1.0,
            "missing_close_counts_in_checkpoint_denominator": True,
        }
        if clv is None:
            row.update(
                {
                    "close_status": "MISSING",
                    "close_observed_at_utc": None,
                    "close_selected_fair_probability": None,
                    "clv_probability_points": None,
                    "close_coverage_value": 0,
                    "missing_close_excluded_from_clv": True,
                }
            )
        else:
            row.update(
                {
                    "close_status": "AVAILABLE",
                    "close_observed_at_utc": close.isoformat(),
                    "close_selected_fair_probability": 0.50 + clv,
                    "clv_probability_points": clv,
                    "close_coverage_value": 1,
                    "missing_close_excluded_from_clv": False,
                }
            )
        return row

    def test_student_t_reference_is_actual_t_not_normal(self):
        self.assertAlmostEqual(_student_t_critical_975(4), 2.7764451052, places=7)
        self.assertGreater(_student_t_critical_975(4), 1.96)

    def test_below_first_checkpoint_waits_and_never_grants_authority(self):
        report = evaluate_v2_checkpoints([self._row(i) for i in range(49)])
        self.assertEqual(report["status"], "WAITING_FOR_FIRST_CHECKPOINT")
        self.assertEqual(report["next_checkpoint_count"], 50)
        self.assertEqual(report["checkpoint_evaluations"], [])
        self.assertIs(report["promotion_authority"], False)
        self.assertIs(report["staking_change_allowed"], False)

    def test_checkpoint_50_uses_frozen_first_50_prefix(self):
        rows = [self._row(i, slate_index=i // 10) for i in range(50)]
        poison = self._row(50, slate_index=5, clv=-0.40, won=False)
        report = evaluate_v2_checkpoints(rows + [poison])
        self.assertEqual(report["crossed_checkpoint_counts"], [50])
        cp = report["checkpoint_evaluations"][0]
        self.assertEqual(cp["graded_bet_count"], 50)
        self.assertEqual(cp["valid_close_count"], 50)
        self.assertAlmostEqual(cp["mean_clv_pp"], 0.02)
        self.assertTrue(cp["metric_gate_pass"])
        self.assertEqual(cp["metric_disposition"], "PROBATION_METRICS_PASS")
        self.assertIs(cp["promotion_authority"], False)

    def test_missing_closes_stay_in_denominator_and_trigger_coverage_rule(self):
        rows = [self._row(i, slate_index=i // 10) for i in range(50)]
        for i in range(6):
            rows[i] = self._row(i, slate_index=i // 10, clv=None)
        cp = evaluate_v2_checkpoints(rows)["checkpoint_evaluations"][0]
        self.assertEqual(cp["graded_bet_count"], 50)
        self.assertEqual(cp["valid_close_count"], 44)
        self.assertEqual(cp["missing_close_count"], 6)
        self.assertAlmostEqual(cp["close_coverage"], 0.88)
        self.assertIn("close_coverage < 0.90", cp["kill_rules_fired"])
        self.assertFalse(cp["metric_gate_pass"])

    def test_checkpoint_100_is_continue_only_and_kill_rule_driven(self):
        rows = [self._row(i, slate_index=i // 10) for i in range(100)]
        report = evaluate_v2_checkpoints(rows)
        self.assertEqual(report["crossed_checkpoint_counts"], [50, 100])
        cp = report["checkpoint_evaluations"][1]
        self.assertEqual(cp["target_state"], "PROBATION_CONTINUE")
        self.assertEqual(cp["metric_disposition"], "PROBATION_CONTINUE_METRICS_PASS")
        self.assertTrue(cp["metric_gate_pass"])

    def test_checkpoint_150_requires_positive_lower_clv_bound(self):
        rows = [self._row(i, slate_index=i // 10) for i in range(150)]
        report = evaluate_v2_checkpoints(rows)
        cp = report["checkpoint_evaluations"][2]
        self.assertEqual(cp["target_state"], "OFFICIAL_CANDIDATE")
        self.assertGreater(cp["clv_95_ci_lower_pp"], 0.0)
        self.assertTrue(cp["metric_gate_pass"])
        self.assertEqual(cp["metric_disposition"], "OFFICIAL_CANDIDATE_METRICS_PASS")
        self.assertEqual(
            cp["official_warning_gate_status"],
            "SEPARATE_REQUIRED_GATE_NOT_ASSERTED_BY_METRIC_EVALUATOR",
        )
        self.assertIs(cp["official_change_allowed"], False)

    def test_legacy_row_is_rejected_not_reinterpreted(self):
        row = self._row(0)
        row["schema_version"] = "mlb_moneyline_forward_evidence_v1"
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "legacy or unknown"):
            evaluate_v2_checkpoints([row])

    def test_duplicate_game_is_hard_failure(self):
        rows = [self._row(i) for i in range(2)]
        rows[1]["game_pk"] = rows[0]["game_pk"]
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "DUPLICATE_OR_MUTATED"):
            evaluate_v2_checkpoints(rows)

    def test_binding_tamper_is_hard_failure(self):
        row = self._row(0)
        row["policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "binding mismatch"):
            evaluate_v2_checkpoints([row])

    def test_model_artifact_change_starts_new_clock(self):
        row = self._row(0)
        row["model_artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "model artifact binding mismatch"):
            evaluate_v2_checkpoints([row])

    def test_slate_date_must_equal_utc_event_start_date(self):
        row = self._row(0)
        row["slate_date"] = "2026-09-18"
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "slate_date"):
            evaluate_v2_checkpoints([row])

    def test_clv_identity_tamper_is_hard_failure(self):
        row = self._row(0)
        row["clv_probability_points"] = 0.99
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "CLV identity mismatch"):
            evaluate_v2_checkpoints([row])

    def test_missing_evidence_tree_is_valid_waiting_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "not-created-yet"
            report = evaluate_evidence_tree(root)
        self.assertEqual(report["status"], "WAITING_FOR_FIRST_CHECKPOINT")
        self.assertEqual(report["total_valid_v2_graded_bets"], 0)
        self.assertEqual(report["source_json_file_count"], 0)
        self.assertIs(report["promotion_authority"], False)

    def test_evidence_tree_loads_cumulative_v2_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            for i in range(3):
                (root / f"{i}.json").write_text(json.dumps(self._row(i)), encoding="utf-8")
            report = evaluate_evidence_tree(root)
        self.assertEqual(report["total_valid_v2_graded_bets"], 3)
        self.assertEqual(report["source_json_file_count"], 3)
        self.assertEqual(report["next_checkpoint_count"], 50)

    def test_runtime_cli_writes_blocked_receipt_on_invalid_json(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            (root / "bad.json").write_text("{not-json", encoding="utf-8")
            report_path = Path(tmp) / "checkpoint.json"
            rc = checkpoint_runtime_main(
                ["--evidence-root", str(root), "--report", str(report_path)]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(report["status"], "BLOCKED_CHECKPOINT_RUNTIME_ERROR")
        self.assertIs(report["promotion_authority"], False)


if __name__ == "__main__":
    unittest.main()
