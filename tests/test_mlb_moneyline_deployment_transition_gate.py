from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from sportsedge.mlb_moneyline_deployment_transition_gate import (
    MLBMoneylineDeploymentTransitionGateError,
    READY_STATUS,
    evaluate_deployment_transition_gate,
)


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MLBMoneylineDeploymentTransitionGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
        self.deployments = {
            "schema_version": 1,
            "markets": {
                "MONEYLINE": {
                    "eligible": False,
                    "stage": "VALIDATED_MATH",
                    "reason": "live production inference path not attested",
                }
            },
        }
        deployment_sha = _canonical_sha256(self.deployments["markets"]["MONEYLINE"])
        self.identity = {
            "lane_id": "MLB_MONEYLINE_DK_T30_V1",
            "model_artifact_sha256": "a" * 64,
            "market_definition_sha256": "b" * 64,
            "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
            "policy_sha256": "c" * 64,
        }
        self.readiness = {
            "schema_version": "mlb_moneyline_transition_readiness_v1",
            "status": "GOVERNANCE_DOCUMENTATION_COMPLETE_FRESH_RUNTIME_STILL_REQUIRED",
            **self.identity,
            "transition_packet_sha256": "d" * 64,
            "deployment_snapshot_sha256": deployment_sha,
            "warning_clearance_status": "OFFICIAL_WARNING_CLEARANCE_PASS",
            "warning_clearance_sha256": "e" * 64,
            "governance_documentation_complete": True,
            "fresh_runtime_hard_checks_required": True,
            "state_transition_apply_now": False,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        self.runtime = {
            "schema_version": "mlb_moneyline_fresh_runtime_hard_checks_v1",
            "status": "FRESH_RUNTIME_HARD_CHECKS_PASS",
            **self.identity,
            "transition_readiness_sha256": _canonical_sha256(self.readiness),
            "deployment_snapshot_sha256": deployment_sha,
            "deployment_eligible_during_check": False,
            "game_pk": 123,
            "provider_event_id": "dk-123",
            "event_start_ts": (self.now + timedelta(minutes=25)).isoformat(),
            "quote_observed_at_utc": (self.now - timedelta(seconds=20)).isoformat(),
            "quote_age_seconds": 10.0,
            "max_quote_age_seconds": 60.0,
            "capture_raw_sha256": "f" * 64,
            "runtime_home_model_p": 0.6,
            "runtime_away_model_p": 0.4,
            "frozen_prediction_home_model_p": 0.6,
            "home_no_vig_probability": 0.52,
            "away_no_vig_probability": 0.48,
            "production_engine_dispatch": "sportsedge.engine_registry.engine_registry[MONEYLINE]",
            "production_home_status": "MODEL_CANDIDATE",
            "production_away_status": "MODEL_CANDIDATE",
            "runtime_checks": {
                "same_frozen_identity": True,
                "active_model_artifact_matches": True,
                "market_blind_prediction_pit_valid": True,
                "draftkings_paired_quote_identity_valid": True,
                "quote_fresh_at_receipt": True,
                "canonical_production_engine_parity": True,
                "two_sided_model_probability_coherence": True,
                "frozen_devig_pair_valid": True,
                "production_candidate_binding_home": True,
                "production_candidate_binding_away": True,
                "deployment_remained_fail_closed": True,
            },
            "state_transition_apply_now": False,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }

    def _evaluate(self, **overrides):
        args = {
            "transition_readiness": self.readiness,
            "fresh_runtime_receipt": self.runtime,
            "deployments": self.deployments,
            "now": self.now,
        }
        args.update(overrides)
        return evaluate_deployment_transition_gate(**args)

    def test_valid_intersection_is_ready_but_non_authoritative(self):
        report = self._evaluate()
        self.assertEqual(report["status"], READY_STATUS)
        self.assertEqual(report["lane_id"], self.identity["lane_id"])
        self.assertFalse(report["deployment_eligible_during_gate"])
        self.assertTrue(all(report["prerequisites"].values()))
        self.assertFalse(report["state_transition_apply_now"])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["deployment_change_allowed"])
        self.assertFalse(report["staking_change_allowed"])
        self.assertFalse(report["official_change_allowed"])

    def test_runtime_identity_drift_fails_closed(self):
        runtime = dict(self.runtime)
        runtime["model_artifact_sha256"] = "9" * 64
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "identity drift"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_runtime_status_must_be_pass(self):
        runtime = dict(self.runtime)
        runtime["status"] = "BLOCKED"
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "did not pass"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_expired_runtime_receipt_fails_closed(self):
        runtime = dict(self.runtime)
        runtime["quote_observed_at_utc"] = (self.now - timedelta(seconds=121)).isoformat()
        with self.assertRaisesRegex(MLBMoneylineDeploymentTransitionGateError, "expired"):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_event_already_started_fails_closed(self):
        runtime = dict(self.runtime)
        runtime["event_start_ts"] = (self.now - timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "before event start"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_eligible_deployment_fails_closed(self):
        deployments = json.loads(json.dumps(self.deployments))
        deployments["markets"]["MONEYLINE"]["eligible"] = True
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "eligible=false"
        ):
            self._evaluate(deployments=deployments)

    def test_authority_bearing_input_fails_closed(self):
        runtime = dict(self.runtime)
        runtime["deployment_change_allowed"] = True
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "forbidden authority"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_readiness_must_bind_exact_runtime_receipt(self):
        runtime = dict(self.runtime)
        runtime["transition_readiness_sha256"] = "7" * 64
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "exact transition readiness"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)

    def test_runtime_check_set_must_all_pass(self):
        runtime = json.loads(json.dumps(self.runtime))
        runtime["runtime_checks"]["canonical_production_engine_parity"] = False
        with self.assertRaisesRegex(
            MLBMoneylineDeploymentTransitionGateError, "check set incomplete"
        ):
            self._evaluate(fresh_runtime_receipt=runtime)


if __name__ == "__main__":
    unittest.main()
