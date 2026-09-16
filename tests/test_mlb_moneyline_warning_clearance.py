from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from sportsedge.mlb_moneyline_warning_clearance import (
    MLBMoneylineWarningClearanceError,
    SCHEMA,
    STATUS,
    validate_warning_clearance,
)


IDENTITY = {
    "lane_id": "MLB_MONEYLINE_DK_T30_V1",
    "model_artifact_sha256": "a" * 64,
    "market_definition_sha256": "b" * 64,
    "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
    "policy_sha256": "c" * 64,
}


def universe():
    policy = json.loads(Path("config/promotion_evidence_policy_v2.json").read_text())
    return list(policy["warning_only_on_probation"])


def receipt():
    stamp = datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc).isoformat()
    warnings = universe()
    return {
        "schema_version": SCHEMA,
        "status": STATUS,
        **IDENTITY,
        "warning_universe": warnings,
        "resolutions": {
            warning: {
                "status": "CLEARED",
                "actor": None,
                "timestamp_utc": stamp,
                "reason": "fixture-only contract evidence",
                "evidence_reference": f"fixture://{warning}",
            }
            for warning in warnings
        },
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


class MLBMoneylineWarningClearanceTest(unittest.TestCase):
    def test_complete_clearance_is_read_only(self):
        out = validate_warning_clearance(receipt(), expected_identity=IDENTITY)
        self.assertEqual(out["status"], STATUS)
        self.assertEqual(out["warning_universe"], universe())
        self.assertIs(out["promotion_authority"], False)
        self.assertIs(out["deployment_change_allowed"], False)
        self.assertIs(out["staking_change_allowed"], False)
        self.assertIs(out["official_change_allowed"], False)

    def test_missing_warning_resolution_fails_closed(self):
        row = receipt()
        row["resolutions"].pop(universe()[0])
        with self.assertRaisesRegex(
            MLBMoneylineWarningClearanceError, "every frozen warning"
        ):
            validate_warning_clearance(row, expected_identity=IDENTITY)

    def test_unresolved_warning_fails_closed(self):
        row = receipt()
        row["resolutions"][universe()[0]]["status"] = "OPEN"
        with self.assertRaisesRegex(MLBMoneylineWarningClearanceError, "warning unresolved"):
            validate_warning_clearance(row, expected_identity=IDENTITY)

    def test_signed_off_requires_actor(self):
        row = receipt()
        row["resolutions"][universe()[0]]["status"] = "SIGNED_OFF"
        row["resolutions"][universe()[0]]["actor"] = None
        with self.assertRaisesRegex(MLBMoneylineWarningClearanceError, "actor missing"):
            validate_warning_clearance(row, expected_identity=IDENTITY)

    def test_identity_drift_fails_closed(self):
        row = receipt()
        row["model_artifact_sha256"] = "d" * 64
        with self.assertRaisesRegex(MLBMoneylineWarningClearanceError, "identity mismatch"):
            validate_warning_clearance(row, expected_identity=IDENTITY)

    def test_receipt_cannot_carry_authority(self):
        row = receipt()
        row["official_change_allowed"] = True
        with self.assertRaisesRegex(MLBMoneylineWarningClearanceError, "non-authoritative"):
            validate_warning_clearance(row, expected_identity=IDENTITY)


if __name__ == "__main__":
    unittest.main()
