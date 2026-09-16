from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.mlb_moneyline_v2_checkpoint import (
    MLBMoneylineV2CheckpointError,
    evaluate_v2_checkpoint,
    student_t_critical_975,
)


class MLBMoneylineV2CheckpointTests(unittest.TestCase):
    def binding(self) -> dict:
        return {
            "lane_id": "MLB_MONEYLINE_DK_T30_V1",
            "lane_definition_sha256": "1" * 64,
            "market_definition_sha256": "2" * 64,
            "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
            "policy_sha256": "3" * 64,
            "policy_manifest_sha256": "4" * 64,
            "edge_floor_config_sha256": "5" * 64,
            "promotion_authority": False,
        }

    def row(self, i: int, *, clv: float | None = 0.01, roi: float = 0.02) -> dict:
        day = i // 5
        start = datetime(2026, 9, 1, 18, tzinfo=timezone.utc) + timedelta(days=day)
        close_available = clv is not None
        return {
            **self.binding(),
            "status": "FORWARD_EVIDENCE_COMPLETE_V2",
            "state": "PAPER",
            "graded_bet": True,
            "evidence_counts": True,
            "stake_units": 0.0,
            "game_pk": 100000 + i,
            "slate_date": start.date().isoformat(),
            "event_start_ts": start.isoformat(),
            "model_artifact_sha256": "a" * 64,
            "decision_record_sha256": f"{i + 1:064x}",
            "close_status": "AVAILABLE" if close_available else "MISSING",
            "clv_probability_points": clv,
            "close_coverage_value": 1 if close_available else 0,
            "paper_roi_fraction_per_1u": roi,
        }

    def test_student_t_critical_df4(self) -> None:
        self.assertAlmostEqual(student_t_critical_975(4), 2.776445, places=5)

    def test_not_checkpoint_never_qualifies(self) -> None:
        report = evaluate_v2_checkpoint([self.row(i) for i in range(49)], binding=self.binding())
        self.assertEqual(report["status"], "NOT_AT_FIXED_CHECKPOINT")
        self.assertFalse(report["qualifies_for_target_state"])
        self.assertFalse(report["promotion_authority"])

    def test_checkpoint_50_can_qualify_only_as_candidate(self) -> None:
        report = evaluate_v2_checkpoint([self.row(i) for i in range(50)], binding=self.binding())
        self.assertEqual(report["checkpoint"], 50)
        self.assertEqual(report["target_state"], "PROBATION")
        self.assertTrue(report["qualifies_for_target_state"])
        self.assertEqual(report["blocking_reasons"], [])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["staking_change_allowed"])

    def test_checkpoint_50_missing_close_coverage_blocks(self) -> None:
        rows = [self.row(i, clv=None if i < 6 else 0.01) for i in range(50)]
        report = evaluate_v2_checkpoint(rows, binding=self.binding())
        self.assertFalse(report["qualifies_for_target_state"])
        self.assertIn("MIN_CLOSE_COVERAGE_NOT_MET", report["blocking_reasons"])

    def test_checkpoint_50_negative_mean_clv_blocks_even_if_ci_upper_positive(self) -> None:
        rows = []
        for i in range(50):
            clv = -0.02 if i % 2 == 0 else 0.019
            rows.append(self.row(i, clv=clv))
        report = evaluate_v2_checkpoint(rows, binding=self.binding())
        self.assertFalse(report["qualifies_for_target_state"])
        self.assertIn("MEAN_CLV_BELOW_CHECKPOINT_50_FLOOR", report["blocking_reasons"])

    def test_checkpoint_150_requires_explicit_warning_attestation(self) -> None:
        report = evaluate_v2_checkpoint([self.row(i) for i in range(150)], binding=self.binding())
        self.assertFalse(report["qualifies_for_target_state"])
        self.assertIn("OFFICIAL_WARNING_REQUIREMENT_NOT_MET", report["blocking_reasons"])
        self.assertFalse(report["warning_gate"]["attested"])

    def test_checkpoint_150_explicit_empty_warning_set_can_pass_metrics(self) -> None:
        report = evaluate_v2_checkpoint(
            [self.row(i) for i in range(150)],
            binding=self.binding(),
            warning_statuses={},
        )
        self.assertTrue(report["qualifies_for_target_state"])
        self.assertEqual(report["target_state"], "OFFICIAL_CANDIDATE")
        self.assertFalse(report["promotion_authority"])

    def test_mixed_model_artifact_fails_closed(self) -> None:
        rows = [self.row(i) for i in range(50)]
        rows[-1]["model_artifact_sha256"] = "b" * 64
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "mixed model artifacts"):
            evaluate_v2_checkpoint(rows, binding=self.binding())

    def test_duplicate_game_fails_closed(self) -> None:
        rows = [self.row(i) for i in range(50)]
        rows[-1]["game_pk"] = rows[0]["game_pk"]
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "duplicate game_pk"):
            evaluate_v2_checkpoint(rows, binding=self.binding())

    def test_slate_date_must_match_utc_event_date(self) -> None:
        rows = [self.row(i) for i in range(50)]
        rows[0]["slate_date"] = "2026-09-30"
        with self.assertRaisesRegex(MLBMoneylineV2CheckpointError, "slate_date"):
            evaluate_v2_checkpoint(rows, binding=self.binding())


if __name__ == "__main__":
    unittest.main()
