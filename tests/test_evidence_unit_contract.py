from __future__ import annotations

import json
from pathlib import Path
import unittest

from sports.common.evidence_unit import (
    EvidenceContractError,
    assert_market_blind_feature_schema,
    assert_model_stage_market_blind,
    canonical_sha256,
    validate_close_observation,
    validate_decision_record,
    validate_evidence_unit_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class EvidenceUnitContractTests(unittest.TestCase):
    def manifest(self):
        h = "a" * 64
        return {
            "artifact_sha256": h,
            "feature_schema_sha256": "b" * 64,
            "predictive_code_manifest_sha256": "c" * 64,
            "acquisition_code_manifest_sha256": "d" * 64,
            "policy_sha256": "e" * 64,
            "close_definition_id": "DK_SAME_LINE_T20_T2_POWER_V1",
        }

    def decision(self, evidence_unit_id: str):
        return {
            "decision_id": "d1",
            "evidence_unit_id": evidence_unit_id,
            "sport": "CFB",
            "lane": "game_spread",
            "game_id": "g1",
            "game_start_ts": "2026-09-12T00:00:00Z",
            "input_manifest_sha256": "f" * 64,
            "model_p": 0.58,
            "model_p_computed_at": "2026-09-11T21:30:00Z",
            "price_observed_at": "2026-09-11T21:20:00Z",
            "book": "draftkings",
            "price_source": "MANUAL_SCREENSHOT",
            "selected_price": -110,
            "opposite_price": -110,
            "candidate_label": "LIKE",
            "certification_status": "CANDIDATE",
            "qualifying_threshold_id": "CFB_GAME_THRESHOLDS_V1",
            "qualifies_for_evidence": True,
            "actual_bet_placed": False,
            "kelly_fraction_information_only": 0.04,
        }

    def test_manifest_identity_is_canonical_and_complete(self):
        value = validate_evidence_unit_manifest(self.manifest())
        self.assertEqual(value["evidence_unit_id"], canonical_sha256({
            key: value[key]
            for key in (
                "artifact_sha256",
                "feature_schema_sha256",
                "predictive_code_manifest_sha256",
                "acquisition_code_manifest_sha256",
                "policy_sha256",
                "close_definition_id",
            )
        }))

    def test_two_sided_candidate_can_be_v2_evidence(self):
        manifest = validate_evidence_unit_manifest(self.manifest())
        row = validate_decision_record(self.decision(manifest["evidence_unit_id"]), expected_evidence_unit_id=manifest["evidence_unit_id"])
        self.assertTrue(row["v2_price_eligible"])

    def test_one_sided_candidate_is_not_v2_evidence(self):
        manifest = validate_evidence_unit_manifest(self.manifest())
        row = self.decision(manifest["evidence_unit_id"])
        row["opposite_price"] = None
        row["qualifies_for_evidence"] = False
        checked = validate_decision_record(row)
        self.assertFalse(checked["v2_price_eligible"])
        self.assertEqual(checked["v2_ineligibility_reason"], "V2_INELIGIBLE_ONE_SIDED")
        row["qualifies_for_evidence"] = True
        with self.assertRaisesRegex(EvidenceContractError, "V2_INELIGIBLE_ONE_SIDED"):
            validate_decision_record(row)

    def test_close_is_separate_pregame_and_same_book(self):
        manifest = validate_evidence_unit_manifest(self.manifest())
        decision = self.decision(manifest["evidence_unit_id"])
        close = {
            "close_id": "c1",
            "decision_id": "d1",
            "observed_at": "2026-09-11T23:55:00Z",
            "book": "draftkings",
            "selected_price": -108,
            "opposite_price": -112,
            "snapshot_sha256": "1" * 64,
        }
        self.assertEqual(validate_close_observation(close, decision=decision)["decision_id"], "d1")

    def test_market_fields_are_rejected_from_feature_schema(self):
        assert_market_blind_feature_schema(["off_epa", "def_success_rate", "rest_days"])
        with self.assertRaisesRegex(EvidenceContractError, "FEATURE_SCHEMA_MARKET_FIELD_FORBIDDEN"):
            assert_market_blind_feature_schema(["off_epa", "closing_odds"])

    def test_model_stage_cannot_import_price_adapter(self):
        assert_model_stage_market_blind("from math import exp\n")
        with self.assertRaisesRegex(EvidenceContractError, "MODEL_STAGE_PRICE_IMPORT_FORBIDDEN"):
            assert_model_stage_market_blind("from sportsedge.sports.nfl.odds_source import fetch_nfl_odds\n")

    def test_shared_contract_file_matches_code_enums(self):
        payload = json.loads((ROOT / "config/evidence_unit_contract_v1.json").read_text())
        self.assertEqual(payload["candidate_labels"], ["LOVE", "LIKE", "WATCH", "NO_PLAY"])
        self.assertEqual(payload["certification_statuses"], ["CANDIDATE", "PROBATION", "OFFICIAL", "BLOCKED"])
        self.assertTrue(payload["v2_price_rule"]["two_sided_required"])
        self.assertFalse(payload["stake_rule"]["kelly_may_size_candidate_stake"])
        self.assertTrue(payload["qualifying_rule"]["record_regardless_of_actual_bet"])


if __name__ == "__main__":
    unittest.main()
