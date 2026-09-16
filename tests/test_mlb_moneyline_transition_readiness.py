from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest

from sportsedge.mlb_moneyline_transition_readiness import (
    MLBMoneylineTransitionReadinessError,
    READY_STATUS,
    WAITING_STATUS,
    evaluate_transition_readiness,
)
from sportsedge.mlb_moneyline_warning_clearance import SCHEMA as WARNING_SCHEMA


IDENTITY = {
    "lane_id": "MLB_MONEYLINE_DK_T30_V1",
    "model_artifact_sha256": "a" * 64,
    "market_definition_sha256": "b" * 64,
    "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
    "policy_sha256": "c" * 64,
}


def sha(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def deployments():
    return {
        "markets": {
            "MONEYLINE": {
                "eligible": False,
                "stage": "VALIDATED_MATH",
                "edge_floor": 0.03,
                "reason": "live production inference path not attested",
            }
        }
    }


def packet():
    moneyline = deployments()["markets"]["MONEYLINE"]
    return {
        "schema_version": "mlb_moneyline_transition_packet_v1",
        "status": "READY_FOR_FRESH_RUNTIME_AND_WARNING_CLEARANCE",
        **IDENTITY,
        "readiness_sha256": "d" * 64,
        "deployment_snapshot_sha256": sha(moneyline),
        "required_transition_receipts": [
            "FRESH_RUNTIME_HARD_CHECKS_PASS",
            "OFFICIAL_WARNING_CLEARANCE_PASS",
        ],
        "proposed_state_change": {
            "market": "MONEYLINE",
            "from_eligible": False,
            "to_eligible": True,
            "apply_now": False,
        },
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def warning_receipt():
    policy = json.loads(Path("config/promotion_evidence_policy_v2.json").read_text())
    universe = list(policy["warning_only_on_probation"])
    stamp = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc).isoformat()
    return {
        "schema_version": WARNING_SCHEMA,
        "status": "OFFICIAL_WARNING_CLEARANCE_PASS",
        **IDENTITY,
        "warning_universe": universe,
        "resolutions": {
            warning: {
                "status": "CLEARED",
                "actor": None,
                "timestamp_utc": stamp,
                "reason": "fixture-only documented clearance",
                "evidence_reference": f"fixture://{warning}",
            }
            for warning in universe
        },
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


class MLBMoneylineTransitionReadinessTest(unittest.TestCase):
    def test_missing_warning_receipt_waits_without_authority(self):
        out = evaluate_transition_readiness(
            transition_packet=packet(), warning_receipt=None, deployments=deployments()
        )
        self.assertEqual(out["status"], WAITING_STATUS)
        self.assertIs(out["governance_documentation_complete"], False)
        self.assertIs(out["fresh_runtime_hard_checks_required"], True)
        self.assertIs(out["state_transition_apply_now"], False)
        self.assertIs(out["official_change_allowed"], False)

    def test_complete_documentation_still_requires_fresh_runtime(self):
        out = evaluate_transition_readiness(
            transition_packet=packet(),
            warning_receipt=warning_receipt(),
            deployments=deployments(),
        )
        self.assertEqual(out["status"], READY_STATUS)
        self.assertIs(out["governance_documentation_complete"], True)
        self.assertIs(out["fresh_runtime_hard_checks_required"], True)
        self.assertIs(out["state_transition_apply_now"], False)
        self.assertIs(out["promotion_authority"], False)
        self.assertIs(out["deployment_change_allowed"], False)
        self.assertIs(out["staking_change_allowed"], False)
        self.assertIs(out["official_change_allowed"], False)

    def test_deployment_drift_fails_closed(self):
        current = deployments()
        current["markets"]["MONEYLINE"]["reason"] = "changed"
        with self.assertRaisesRegex(
            MLBMoneylineTransitionReadinessError, "deployment snapshot drift"
        ):
            evaluate_transition_readiness(
                transition_packet=packet(),
                warning_receipt=warning_receipt(),
                deployments=current,
            )

    def test_premature_eligibility_fails_closed(self):
        current = deployments()
        current["markets"]["MONEYLINE"]["eligible"] = True
        with self.assertRaisesRegex(
            MLBMoneylineTransitionReadinessError, "remain fail closed"
        ):
            evaluate_transition_readiness(
                transition_packet=packet(), warning_receipt=None, deployments=current
            )

    def test_warning_identity_drift_fails_closed(self):
        warning = warning_receipt()
        warning["policy_sha256"] = "e" * 64
        with self.assertRaisesRegex(
            MLBMoneylineTransitionReadinessError, "identity mismatch"
        ):
            evaluate_transition_readiness(
                transition_packet=packet(), warning_receipt=warning, deployments=deployments()
            )

    def test_transition_packet_cannot_carry_authority(self):
        value = packet()
        value["official_change_allowed"] = True
        with self.assertRaisesRegex(
            MLBMoneylineTransitionReadinessError, "non-authoritative"
        ):
            evaluate_transition_readiness(
                transition_packet=value, warning_receipt=None, deployments=deployments()
            )


if __name__ == "__main__":
    unittest.main()
