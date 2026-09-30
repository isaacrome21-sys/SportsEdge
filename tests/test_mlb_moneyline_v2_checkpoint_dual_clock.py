"""Dual-clock split: prior-engine evidence is closed, never pooled into active clock."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sportsedge.mlb_moneyline_v2_checkpoint_runtime import evaluate_v2_checkpoints


ACTIVE_HASH = "a" * 64
PRIOR_HASH = "b" * 64


def _minimal_row(*, model_hash: str, game_pk: int, slate: str = "2026-09-01") -> dict:
    """Bare row for the runtime split layer only (before full checkpoint validation)."""
    return {
        "model_artifact_sha256": model_hash,
        "event_start_ts": f"{slate}T23:05:00+00:00",
        "slate_date": slate,
        "game_pk": game_pk,
    }


class MoneylineV2DualClockTests(unittest.TestCase):
    def test_prior_and_current_hashes_are_reported_separately(self):
        rows = [
            _minimal_row(model_hash=PRIOR_HASH, game_pk=1),
            _minimal_row(model_hash=PRIOR_HASH, game_pk=2),
            _minimal_row(model_hash=ACTIVE_HASH, game_pk=3),
        ]
        fake_report = {
            "schema_version": "mlb_moneyline_promotion_checkpoint_v2",
            "total_valid_v2_graded_bets": 0,
            "status": "WAITING_FOR_FIRST_CHECKPOINT",
            "model_artifact_sha256": ACTIVE_HASH,
            "checkpoint_evaluations": [],
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }

        with patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime.mlb_model_artifact_sha256",
            return_value=ACTIVE_HASH,
        ), patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime._evaluate_v2_checkpoints",
            return_value=dict(fake_report),
        ) as mock_eval, patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime.load_forward_lane_binding",
            return_value={
                "lane_id": "MLB_MONEYLINE_V2",
                "model_artifact_sha256": ACTIVE_HASH,
                "market_definition_sha256": "c" * 64,
                "policy_sha256": "d" * 64,
            },
        ):
            report = evaluate_v2_checkpoints(rows)

        # Only the current-hash row reaches the active evaluator.
        self.assertEqual(mock_eval.call_count, 1)
        evaluated_rows = list(mock_eval.call_args.args[0])
        self.assertEqual(len(evaluated_rows), 1)
        self.assertEqual(evaluated_rows[0]["model_artifact_sha256"], ACTIVE_HASH)
        self.assertEqual(evaluated_rows[0]["game_pk"], 3)

        self.assertEqual(report["active_model_artifact_sha256"], ACTIVE_HASH)
        self.assertEqual(report["active_clock_row_count"], 1)
        self.assertEqual(report["closed_prior_engine_row_count"], 2)
        self.assertTrue(report["prior_engine_rows_excluded_from_active_clock"])
        sections = report["closed_prior_engine_sections"]
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["model_artifact_sha256"], PRIOR_HASH)
        self.assertEqual(sections[0]["row_count"], 2)
        self.assertEqual(sections[0]["status"], "CLOSED_UNDER_PRIOR_ENGINE")

    def test_all_prior_rows_yield_empty_active_clock(self):
        rows = [
            _minimal_row(model_hash=PRIOR_HASH, game_pk=10),
            _minimal_row(model_hash=PRIOR_HASH, game_pk=11),
        ]
        fake_report = {
            "schema_version": "mlb_moneyline_promotion_checkpoint_v2",
            "total_valid_v2_graded_bets": 0,
            "status": "WAITING_FOR_FIRST_CHECKPOINT",
            "model_artifact_sha256": ACTIVE_HASH,
            "checkpoint_evaluations": [],
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }

        with patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime.mlb_model_artifact_sha256",
            return_value=ACTIVE_HASH,
        ), patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime._evaluate_v2_checkpoints",
            return_value=dict(fake_report),
        ) as mock_eval, patch(
            "sportsedge.mlb_moneyline_v2_checkpoint_runtime.load_forward_lane_binding",
            return_value={
                "lane_id": "MLB_MONEYLINE_V2",
                "model_artifact_sha256": ACTIVE_HASH,
                "market_definition_sha256": "c" * 64,
                "policy_sha256": "d" * 64,
            },
        ):
            report = evaluate_v2_checkpoints(rows)

        evaluated_rows = list(mock_eval.call_args.args[0])
        self.assertEqual(evaluated_rows, [])
        self.assertEqual(report["active_clock_row_count"], 0)
        self.assertEqual(report["closed_prior_engine_row_count"], 2)


if __name__ == "__main__":
    unittest.main()
