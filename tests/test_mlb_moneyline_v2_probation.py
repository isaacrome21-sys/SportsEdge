from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
from sportsedge.mlb_moneyline_forward_lane import load_forward_lane_binding
from sportsedge.mlb_moneyline_v2_checkpoint import CHECKPOINT_REPORT_SCHEMA, POLICY_ID
from sportsedge.mlb_moneyline_v2_probation import (
    ATTESTATION_SCHEMA,
    MLBMoneylineV2ProbationError,
    evaluate_probation_readiness,
)
from sportsedge.mlb_moneyline_v2_probation_runtime import main as probation_runtime_main


class MLBMoneylineV2ProbationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binding = load_forward_lane_binding()
        cls.artifact = mlb_model_artifact_sha256()
        cls.active = {
            "lane_id": cls.binding["lane_id"],
            "model_artifact_sha256": cls.artifact,
            "market_definition_sha256": cls.binding["market_definition_sha256"],
            "policy_sha256": cls.binding["policy_sha256"],
        }

    def _lineage(self) -> list[str]:
        return [f"{i + 1:064x}" for i in range(50)]

    def _report(self, *, crossed: bool = True, metric_pass: bool = True) -> dict:
        evaluations = []
        total = 49
        crossed_counts = []
        if crossed:
            lineage = self._lineage()
            sample = hashlib.sha256("\n".join(lineage).encode("ascii")).hexdigest()
            evaluations = [
                {
                    "checkpoint_count": 50,
                    "target_state": "PROBATION",
                    "graded_bet_count": 50,
                    "metric_gate_pass": metric_pass,
                    "metric_disposition": "PROBATION_METRICS_PASS" if metric_pass else "PAPER_METRICS_FAIL",
                    "kill_rules_fired": [] if metric_pass else ["close_coverage < 0.90"],
                    "evidence_record_sha256s": lineage,
                    "checkpoint_sample_sha256": sample,
                    "promotion_authority": False,
                }
            ]
            total = 50
            crossed_counts = [50]
        return {
            "schema_version": CHECKPOINT_REPORT_SCHEMA,
            "policy_id": POLICY_ID,
            **self.active,
            "total_valid_v2_graded_bets": total,
            "crossed_checkpoint_counts": crossed_counts,
            "checkpoint_evaluations": evaluations,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }

    def _attestation(self, report: dict, *, failing: str | None = None) -> dict:
        required = [
            "frozen_lane_definition",
            "genuine_model_p_from_frozen_artifact",
            "working_two_sided_pregame_capture",
            "working_two_sided_close_capture",
        ]
        requirements = {}
        for name in required:
            requirements[name] = {
                "status": "FAIL" if name == failing else "PASS",
                "evidence_reference": f"github://evidence/{name}",
            }
        return {
            "schema_version": ATTESTATION_SCHEMA,
            "policy_id": POLICY_ID,
            **self.active,
            "checkpoint_sample_sha256": report["checkpoint_evaluations"][0]["checkpoint_sample_sha256"],
            "requirements": requirements,
        }

    def test_waiting_for_checkpoint_50_is_non_authoritative(self):
        result = evaluate_probation_readiness(self._report(crossed=False))
        self.assertEqual(result["status"], "WAITING_FOR_CHECKPOINT_50")
        self.assertFalse(result["transition_ready_for_authority_review"])
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["staking_change_allowed"])

    def test_metric_pass_without_prerequisite_attestation_remains_not_ready(self):
        result = evaluate_probation_readiness(self._report())
        self.assertEqual(result["status"], "PROBATION_TRANSITION_NOT_READY")
        self.assertEqual(len(result["blocking_reasons"]), 4)
        self.assertFalse(result["transition_ready_for_authority_review"])

    def test_metric_failure_blocks_even_with_all_prerequisites_passed(self):
        report = self._report(metric_pass=False)
        result = evaluate_probation_readiness(
            report,
            prerequisite_attestation=self._attestation(report),
        )
        self.assertIn("CHECKPOINT_50_METRICS_NOT_MET", result["blocking_reasons"])
        self.assertFalse(result["transition_ready_for_authority_review"])

    def test_all_prerequisites_can_make_readiness_true_but_never_grant_authority(self):
        report = self._report()
        result = evaluate_probation_readiness(
            report,
            prerequisite_attestation=self._attestation(report),
        )
        self.assertEqual(result["status"], "PROBATION_TRANSITION_READY_FOR_AUTHORITY_REVIEW")
        self.assertTrue(result["transition_ready_for_authority_review"])
        self.assertEqual(result["blocking_reasons"], [])
        self.assertEqual(result["stake_units_per_bet_from_policy"], 0.25)
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["deployment_change_allowed"])
        self.assertFalse(result["staking_change_allowed"])
        self.assertFalse(result["official_change_allowed"])

    def test_one_failed_prerequisite_blocks(self):
        report = self._report()
        result = evaluate_probation_readiness(
            report,
            prerequisite_attestation=self._attestation(report, failing="working_two_sided_close_capture"),
        )
        self.assertIn(
            "PREREQUISITE_NOT_PASS:working_two_sided_close_capture",
            result["blocking_reasons"],
        )
        self.assertFalse(result["transition_ready_for_authority_review"])

    def test_checkpoint_sample_tamper_fails_closed(self):
        report = self._report()
        report["checkpoint_evaluations"][0]["checkpoint_sample_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineV2ProbationError, "sample SHA mismatch"):
            evaluate_probation_readiness(report)

    def test_active_identity_mismatch_fails_closed(self):
        report = self._report()
        report["model_artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineV2ProbationError, "active identity mismatch"):
            evaluate_probation_readiness(report)

    def test_pass_prerequisite_requires_evidence_reference(self):
        report = self._report()
        attestation = self._attestation(report)
        attestation["requirements"]["frozen_lane_definition"]["evidence_reference"] = ""
        with self.assertRaisesRegex(MLBMoneylineV2ProbationError, "requires evidence reference"):
            evaluate_probation_readiness(report, prerequisite_attestation=attestation)

    def test_attestation_is_bound_to_checkpoint_sample(self):
        report = self._report()
        attestation = self._attestation(report)
        attestation["checkpoint_sample_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineV2ProbationError, "attestation checkpoint mismatch"):
            evaluate_probation_readiness(report, prerequisite_attestation=attestation)

    def test_runtime_writes_waiting_receipt_without_attestation(self):
        with TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            output = Path(tmp) / "readiness.json"
            checkpoint.write_text(json.dumps(self._report(crossed=False)), encoding="utf-8")
            rc = probation_runtime_main([
                "--checkpoint-report", str(checkpoint),
                "--report", str(output),
            ])
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(result["status"], "WAITING_FOR_CHECKPOINT_50")
        self.assertFalse(result["promotion_authority"])

    def test_runtime_invalid_checkpoint_writes_blocked_receipt(self):
        with TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "checkpoint.json"
            output = Path(tmp) / "readiness.json"
            checkpoint.write_text("{}", encoding="utf-8")
            rc = probation_runtime_main([
                "--checkpoint-report", str(checkpoint),
                "--report", str(output),
            ])
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertEqual(result["status"], "BLOCKED_PROBATION_READINESS_INTEGRITY_ERROR")
        self.assertFalse(result["transition_ready_for_authority_review"])


if __name__ == "__main__":
    unittest.main()
