import copy
import unittest

from sportsedge.mlb_moneyline_transition_packet import (
    MLBMoneylineTransitionPacketError,
    build_transition_packet,
)


class TransitionPacketTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {
            "markets": {
                "MONEYLINE": {
                    "eligible": False,
                    "stage": "VALIDATED_MATH",
                    "reason": "live production inference path not attested",
                }
            }
        }
        self.readiness = {
            "schema_version": "mlb_moneyline_authority_readiness_v1",
            "status": "TERMINAL_EVIDENCE_PREREQUISITES_OBSERVED_TRANSITION_STILL_REQUIRED",
            "all_terminal_evidence_prerequisites_observed": True,
            "lane_id": "MLB_MONEYLINE_DK_T30_V1",
            "model_artifact_sha256": "a" * 64,
            "market_definition_sha256": "b" * 64,
            "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
            "policy_sha256": "c" * 64,
            "checks": {
                "frozen_nonzero_edge_floor": True,
                "checkpoint_50_probation_prerequisites_ready_for_authority_review": True,
                "prospective_calibration_min_200_and_band_pass": True,
                "v2_checkpoint_150_official_candidate_metrics_pass": True,
                "model_directed_no_vig_close_edge_at_least_0_005": True,
                "deployment_remains_fail_closed_until_transition": True,
            },
            "deployment_snapshot": {
                "eligible": False,
                "stage": "VALIDATED_MATH",
                "reason": "live production inference path not attested",
            },
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }

    def test_ready_receipt_yields_non_authoritative_candidate(self):
        packet = build_transition_packet(
            readiness=self.readiness, deployments=self.deployment
        )
        self.assertEqual(
            packet["status"], "READY_FOR_FRESH_RUNTIME_AND_WARNING_CLEARANCE"
        )
        self.assertFalse(packet["proposed_state_change"]["apply_now"])
        self.assertTrue(packet["proposed_state_change"]["to_eligible"])
        for key in (
            "promotion_authority",
            "deployment_change_allowed",
            "staking_change_allowed",
            "official_change_allowed",
        ):
            self.assertIs(packet[key], False)

    def test_incomplete_readiness_fails_closed(self):
        receipt = copy.deepcopy(self.readiness)
        receipt["checks"]["prospective_calibration_min_200_and_band_pass"] = False
        with self.assertRaisesRegex(
            MLBMoneylineTransitionPacketError,
            "terminal evidence prerequisites not observed",
        ):
            build_transition_packet(readiness=receipt, deployments=self.deployment)

    def test_deployment_drift_fails_closed(self):
        deployments = copy.deepcopy(self.deployment)
        deployments["markets"]["MONEYLINE"]["reason"] = "changed"
        with self.assertRaisesRegex(
            MLBMoneylineTransitionPacketError, "deployment snapshot drift"
        ):
            build_transition_packet(readiness=self.readiness, deployments=deployments)

    def test_preexisting_eligibility_fails_closed(self):
        deployments = copy.deepcopy(self.deployment)
        deployments["markets"]["MONEYLINE"]["eligible"] = True
        receipt = copy.deepcopy(self.readiness)
        receipt["deployment_snapshot"]["eligible"] = True
        with self.assertRaisesRegex(
            MLBMoneylineTransitionPacketError,
            "MONEYLINE must remain fail closed before transition",
        ):
            build_transition_packet(readiness=receipt, deployments=deployments)

    def test_authoritative_readiness_receipt_is_rejected(self):
        receipt = copy.deepcopy(self.readiness)
        receipt["deployment_change_allowed"] = True
        with self.assertRaisesRegex(
            MLBMoneylineTransitionPacketError,
            "readiness receipt must remain non-authoritative",
        ):
            build_transition_packet(readiness=receipt, deployments=self.deployment)


if __name__ == "__main__":
    unittest.main()
