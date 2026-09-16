from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.mlb_moneyline_authority_readiness import (
    MLBMoneylineAuthorityReadinessError,
    evaluate_authority_readiness,
)
from sportsedge.mlb_moneyline_forward_lane import load_forward_lane_binding


ARTIFACT = "b" * 64


def floors():
    return json.loads(Path("config/truth_gate_floors.json").read_text(encoding="utf-8"))


def deployment(eligible=False):
    return {"markets": {"MONEYLINE": {"eligible": eligible, "stage": "VALIDATED_MATH"}}}


def calibration(passed=True):
    return {
        "model_artifact_sha256": ARTIFACT,
        "calibration_metrics": {
            "evidence_version": "mlb_moneyline_evidence_v1",
            "n": 200 if passed else 199,
            "brier": 0.22,
            "log_loss": 0.64,
            "calibration_slope": 1.0,
            "calibration_intercept": 0.0,
            "ece": 0.02,
            "thresholds": {
                "min_sample": 200,
                "slope": [0.9, 1.1],
                "abs_intercept_max": 0.03,
                "ece_max": 0.025,
            },
            "sample_gate_pass": passed,
            "calibration_gate_pass": passed,
            "promotion_authority": False,
        },
    }


def checkpoint(passed=True):
    item = {
        "checkpoint_count": 150,
        "graded_bet_count": 150,
        "close_coverage": 0.95,
        "clv_95_ci_lower_pp": 0.002 if passed else -0.002,
        "roi_fraction_per_1u": 0.01,
        "metric_gate_pass": passed,
        "metric_disposition": "OFFICIAL_CANDIDATE_METRICS_PASS" if passed else "OFFICIAL_CANDIDATE_METRICS_FAIL",
    }
    return {
        "model_artifact_sha256": ARTIFACT,
        "checkpoint_evaluations": [item],
        "promotion_authority": False,
    }


def evidence():
    return [{
        "schema_version": "mlb_moneyline_forward_evidence_v2",
        "status": "FORWARD_EVIDENCE_COMPLETE_V2",
        "close_status": "AVAILABLE",
        "model_artifact_sha256": ARTIFACT,
        "game_pk": 1,
        "model_side": "HOME",
        "model_p": 0.60,
        "close_home_odds": -110,
        "close_away_odds": -110,
    }]


class AuthorityReadinessTest(unittest.TestCase):
    def test_checkpoint_candidate_is_not_enough_without_200_calibration_rows(self):
        out = evaluate_authority_readiness(
            calibration_report=calibration(False),
            checkpoint_report=checkpoint(True),
            evidence_rows=evidence(),
            deployments=deployment(False),
            floor_config=floors(),
            binding=load_forward_lane_binding(),
        )
        self.assertFalse(out["all_terminal_evidence_prerequisites_observed"])
        self.assertEqual(out["status"], "WAITING_FOR_CALIBRATION_GATE")
        self.assertFalse(out["deployment_change_allowed"])
        self.assertFalse(out["official_change_allowed"])

    def test_all_metric_prerequisites_still_do_not_grant_authority(self):
        out = evaluate_authority_readiness(
            calibration_report=calibration(True),
            checkpoint_report=checkpoint(True),
            evidence_rows=evidence(),
            deployments=deployment(False),
            floor_config=floors(),
            binding=load_forward_lane_binding(),
        )
        self.assertTrue(out["all_terminal_evidence_prerequisites_observed"])
        self.assertEqual(
            out["status"],
            "TERMINAL_EVIDENCE_PREREQUISITES_OBSERVED_TRANSITION_STILL_REQUIRED",
        )
        self.assertFalse(out["promotion_authority"])
        self.assertFalse(out["deployment_change_allowed"])
        self.assertFalse(out["staking_change_allowed"])
        self.assertFalse(out["official_change_allowed"])

    def test_premature_eligible_true_is_hard_failure(self):
        with self.assertRaises(MLBMoneylineAuthorityReadinessError):
            evaluate_authority_readiness(
                calibration_report=calibration(False),
                checkpoint_report=checkpoint(False),
                evidence_rows=[],
                deployments=deployment(True),
                floor_config=floors(),
                binding=load_forward_lane_binding(),
            )


if __name__ == "__main__":
    unittest.main()
