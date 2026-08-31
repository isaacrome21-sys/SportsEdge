from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from sportsedge.core.certification_lifecycle import (
    CertificationLifecycleError,
    RepromotionEvidence,
    StructuralChangeEvent,
    apply_structural_change,
    repromote_from_revoked,
)
from sportsedge.core.decision_provenance import (
    DecisionProvenance,
    DecisionProvenanceError,
    require_same_math_identity,
)
from sportsedge.core.probability_contract import (
    ProbabilityContractError,
    PushAwareProbability,
    ev_per_dollar,
    push_conditioned_edge,
    require_monte_carlo_precision,
)
from sportsedge.mlb_evidence_invalidation import (
    MLBEvidenceFingerprint,
    MLBMarketDependencies,
    evaluate_mlb_evidence_change,
)


HEX_A = "a" * 64
HEX_B = "b" * 64


class ProbabilityBasisTests(unittest.TestCase):
    def test_push_conditioned_edge_uses_same_basis(self):
        model = PushAwareProbability(p_win=0.52, p_push=0.04, p_loss=0.44)
        self.assertAlmostEqual(model.p_win_nonpush, 0.52 / 0.96)
        self.assertAlmostEqual(push_conditioned_edge(model, 0.50), 0.52 / 0.96 - 0.50)
        self.assertAlmostEqual(ev_per_dollar(model, -110), 0.52 * (100 / 110) - 0.44)

    def test_invalid_probability_mass_fails_closed(self):
        with self.assertRaisesRegex(ProbabilityContractError, "MASS_NOT_ONE"):
            PushAwareProbability(0.55, 0.10, 0.40).validate()

    def test_mc_precision_is_enforced_relative_to_edge_floor(self):
        # p=.50 at 10,000 paths has SE=.005. This passes MLB 2.5% floor at the
        # frozen 20% SE/floor ratio (.005 limit) but fails if paths are too small.
        self.assertAlmostEqual(require_monte_carlo_precision(0.50, paths=10000, live_edge_floor=0.025), 0.005)
        with self.assertRaisesRegex(ProbabilityContractError, "MC_PRECISION_INSUFFICIENT"):
            require_monte_carlo_precision(0.50, paths=2500, live_edge_floor=0.025)


class CertificationLifecycleTests(unittest.TestCase):
    def test_material_structural_change_revokes_without_waiting_for_statistics(self):
        event = StructuralChangeEvent(
            event_id="rule-1",
            sport="CFB",
            effective_at="2027-01-01T00:00:00Z",
            change_code="OVERTIME_FORMAT_CHANGE",
            material=True,
            evidence_ref="NCAA_RULEBOOK_2027",
        )
        self.assertEqual(apply_structural_change("OFFICIAL", event), "REVOKED")

    def test_repromotion_requires_complete_new_evidence(self):
        complete = RepromotionEvidence(True, True, True, True, True, True)
        self.assertEqual(repromote_from_revoked("REVOKED", complete), "OFFICIAL")
        with self.assertRaisesRegex(CertificationLifecycleError, "INCOMPLETE"):
            repromote_from_revoked("REVOKED", replace(complete, full_pit_replay_complete=False))


class ProvenanceTests(unittest.TestCase):
    def provenance(self, mode="MANUAL", model_code_sha=HEX_A):
        return DecisionProvenance(
            sport="CFB",
            mode=mode,
            model_code_sha=model_code_sha,
            model_artifact_sha=HEX_A,
            feature_schema_version="CFB_FEATURE_V2",
            feature_schema_sha=HEX_A,
            calibrator_sha=HEX_A,
            simulation_artifact_sha=HEX_A,
            seed_policy="GAME_ID_POLICY_SHA_V1",
            policy_sha=HEX_A,
            benchmark_methodology_sha=HEX_A,
            evidence_gate_sha=HEX_A,
            data_cutoff="2026-08-29T12:00:00Z",
        )

    def test_manual_hybrid_same_math_identity(self):
        manual = self.provenance("MANUAL")
        hybrid = self.provenance("HYBRID")
        require_same_math_identity(manual, hybrid)
        self.assertEqual(manual.model_bundle_hash(), hybrid.model_bundle_hash())

    def test_model_code_drift_fails_identity(self):
        with self.assertRaisesRegex(DecisionProvenanceError, "MODEL_BUNDLE_MISMATCH"):
            require_same_math_identity(self.provenance("MANUAL"), self.provenance("HYBRID", model_code_sha=HEX_B))


class MLBEvidenceInvalidationTests(unittest.TestCase):
    def fp(self, pitcher=10, away_lineup="a", game_number=1):
        return MLBEvidenceFingerprint(
            game_id="123",
            game_number=game_number,
            doubleheader_code="N",
            away_probable_pitcher_id=pitcher,
            home_probable_pitcher_id=20,
            away_lineup_hash=away_lineup,
            home_lineup_hash="h",
            evidence_asof="2026-08-29T12:00:00Z",
        )

    def test_pitcher_change_invalidates(self):
        result = evaluate_mlb_evidence_change(self.fp(), self.fp(pitcher=11))
        self.assertTrue(result.invalidated)
        self.assertIn("STARTING_PITCHER_CHANGED", result.reasons)
        self.assertEqual(result.required_action, "RECOMPUTE_OR_BLOCK")

    def test_lineup_change_can_be_dependency_scoped(self):
        result = evaluate_mlb_evidence_change(
            self.fp(),
            self.fp(away_lineup="b"),
            dependencies=MLBMarketDependencies(starting_pitchers=True, confirmed_lineups=False, game_identity=True),
        )
        self.assertFalse(result.invalidated)


class FrozenConfigTests(unittest.TestCase):
    def load(self, name):
        return json.loads(Path("config", name).read_text())

    def test_cfb_numeric_ttl_and_key_number_tolerance_are_explicit(self):
        quote = self.load("cfb_quote_sync_v1.json")
        validation = self.load("cfb_validation_policy_v1.json")
        self.assertEqual(quote["live"]["max_quote_age_seconds"], 180)
        self.assertEqual(quote["live"]["max_pair_timestamp_skew_seconds"], 30)
        self.assertEqual(validation["key_number_calibration"]["absolute_mass_tolerance"], 0.015)

    def test_mlb_truth_gate_is_numeric_and_fail_closed(self):
        gate = self.load("mlb_truth_gate_v1.json")["hard_gates"]
        self.assertEqual(gate["edge_floor"], 0.025)
        self.assertEqual(gate["min_forward_seasons"], 3)
        self.assertEqual(gate["min_clv_t_stat"], 2.0)
        self.assertEqual(gate["max_ece"], 0.025)
        self.assertTrue(gate["require_model_code_sha"])
        self.assertTrue(gate["require_structural_change_clearance"])

    def test_cross_document_ece_resolution_is_explicit(self):
        policy = self.load("manual_hybrid_governance_v1.json")
        cfb = policy["resolved_thresholds"]["CFB"]
        self.assertEqual(cfb["overall_ece_hard_max"], 0.025)
        self.assertEqual(cfb["actionable_edge_ece_diagnostic_max"], 0.035)
        self.assertEqual(cfb["actionable_edge_ece_status"], "DIAGNOSTIC_ONLY_UNTIL_SEPARATELY_PROMOTED")

    def test_mlb_distribution_mass_contract_is_explicit(self):
        validation = self.load("mlb_validation_policy_v1.json")
        self.assertEqual(validation["distribution_calibration"]["TOTALS"]["total_run_values"], [7, 8, 9])
        self.assertEqual(validation["distribution_calibration"]["RUN_LINE"]["game_margin_values"], [-1, 1])
        self.assertEqual(validation["distribution_calibration"]["TOTALS"]["absolute_mass_tolerance"], 0.015)


if __name__ == "__main__":
    unittest.main()
