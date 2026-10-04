import hashlib
import json
import math
import unittest
from pathlib import Path

from scripts.build_nfl_v2k_reference_v2_proposal import SIGNED_KEYS, wilson95

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "sportsedge/sports/nfl/NFL_V2K_EMPIRICAL_KEY_REFERENCE_V2_PROPOSAL.json"
FROZEN_V1 = ROOT / "sportsedge/sports/nfl/NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json"
LEDGER = ROOT / "sportsedge/sports/nfl/NFL_V2K_ATTEMPT_LEDGER_V1.json"
BUILDER = ROOT / "scripts/build_nfl_v2k_reference_v2_proposal.py"


class NflV2KReferenceV2ProposalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
        cls.v1 = json.loads(FROZEN_V1.read_text(encoding="utf-8"))
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_proposal_is_report_only_and_requires_human_review(self):
        self.assertEqual(self.proposal["status"], "PROPOSED_HUMAN_REVIEW_REQUIRED")
        self.assertEqual(self.proposal["authority"], "NONE")
        self.assertFalse(self.proposal["implementation_admitted"])
        self.assertIsNone(self.proposal["selected_policy"])
        self.assertIsNone(self.proposal["review_decision"])
        review = self.proposal["human_review_contract"]
        self.assertTrue(review["required"])
        self.assertTrue(review["automation_may_not_select_policy"])
        self.assertTrue(review["automation_may_not_approve_version_bump"])
        self.assertTrue(review["automation_may_not_admit_implementation"])

    def test_human_reviewed_v1_freeze_does_not_admit_implementation(self):
        self.assertEqual(self.v1["schema"], "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1")
        self.assertEqual(self.v1["status"], "FROZEN_READY")
        self.assertEqual(self.v1["authority"], "REFERENCE_ONLY")
        self.assertEqual(self.v1["selected_policy"], "MODERN_REG_2018_2025")
        self.assertEqual(self.v1["reference"]["season_scope"], "2018-2025 REG")
        modern = self.proposal["evidence_profiles"]["MODERN_REG_2018_2025"]
        self.assertEqual(self.v1["reference"]["game_count"], modern["game_count"])
        for key in SIGNED_KEYS:
            self.assertAlmostEqual(
                self.v1["reference"]["signed_margin_mass"][str(key)],
                modern["signed_margin_mass"][str(key)]["probability"],
                places=15,
            )
        self.assertTrue(all(v is False for v in self.v1["authority_boundary"].values()))
        # The report-only proposal builder itself did not mutate V1; this later
        # reviewed freeze is a separate governance action and grants no candidate authority.
        self.assertFalse(self.proposal["build_attestation"]["frozen_v1_reference_mutated"])
        self.assertFalse(self.proposal["implementation_admitted"])

    def test_attempt_ledger_remains_frozen_before_implementation(self):
        self.assertEqual(self.ledger["status"], "FROZEN_BEFORE_IMPLEMENTATION")
        self.assertEqual(self.ledger["attempts_used"], 0)
        self.assertFalse(self.ledger["untouched_readout_allowed"])
        self.assertEqual(self.ledger["attempts"], [])
        self.assertTrue(all(v is False for v in self.ledger["authority"].values()))

    def test_both_conflicting_reference_windows_are_reported_without_default(self):
        profiles = self.proposal["evidence_profiles"]
        self.assertEqual(set(profiles), {"MODERN_REG_2018_2025", "BROAD_ALL_2002_2025"})
        self.assertEqual(profiles["MODERN_REG_2018_2025"]["game_count"], 2127)
        self.assertEqual(profiles["BROAD_ALL_2002_2025"]["game_count"], 6499)
        self.assertIsNone(self.proposal["selected_policy"])

    def test_per_key_uncertainty_and_control_metrics_recompute(self):
        for profile in self.proposal["evidence_profiles"].values():
            n = profile["game_count"]
            for key in SIGNED_KEYS:
                row = profile["signed_margin_mass"][str(key)]
                p = row["count"] / n
                self.assertAlmostEqual(row["probability"], p, places=15)
                self.assertAlmostEqual(row["standard_error"], math.sqrt(p * (1.0 - p) / n), places=15)
                low, high = wilson95(row["count"], n)
                self.assertAlmostEqual(row["ci95_low"], low, places=15)
                self.assertAlmostEqual(row["ci95_high"], high, places=15)
            control = profile["control_metrics"]
            slope = control["calibration_slope"]
            self.assertAlmostEqual(control["calibration_slope_metric"], abs(slope - 1.0), places=15)
            rmse = math.sqrt(
                sum(
                    (control["signed_key_probability"][str(k)] - profile["signed_margin_mass"][str(k)]["probability"]) ** 2
                    for k in SIGNED_KEYS
                ) / len(SIGNED_KEYS)
            )
            self.assertAlmostEqual(control["signed_key_mass_rmse"], rmse, places=15)

    def test_structural_gate_requires_both_dimensions_but_is_not_approved(self):
        gate = self.proposal["proposed_structural_improvement_gate"]
        self.assertEqual(gate["status"], "PROPOSED_HUMAN_REVIEW_REQUIRED")
        self.assertTrue(gate["candidate_must_strictly_improve_calibration_slope_metric"])
        self.assertTrue(gate["candidate_must_strictly_improve_signed_key_mass_metric"])
        self.assertFalse(gate["either_dimension_alone_counts_as_pass"])
        self.assertTrue(gate["absolute_per_key_tolerance_still_required"])

    def test_builder_and_source_provenance_are_bound(self):
        source = self.proposal["source_provenance"]
        self.assertEqual(hashlib.sha256(BUILDER.read_bytes()).hexdigest(), source["builder_code_sha256"])
        self.assertEqual(source["games_sha256"], "902f1a3796d576ee846e2b54e99b46a5ab1bdd17bd34c93e8f9f1f797f61281e")
        self.assertEqual(source["evidence_artifact_id"], 10319922606)
        self.assertEqual(
            source["evidence_artifact_digest"],
            "sha256:e53f16804c74ec197b23dd17180ad88d1c696d4a93e593ecc17fa8ccf480a437",
        )
        att = self.proposal["build_attestation"]
        self.assertFalse(att["frozen_v1_reference_mutated"])
        self.assertFalse(att["attempt_ledger_mutated"])
        self.assertFalse(att["automation_selected_policy"])
        self.assertFalse(att["automation_granted_authority"])


if __name__ == "__main__":
    unittest.main()
