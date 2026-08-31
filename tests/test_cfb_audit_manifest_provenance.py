from __future__ import annotations

import unittest
from dataclasses import replace

from sportsedge.sports.cfb.audit_contracts import CFBAuditContractError, CFBAuditManifest


HEX = "a" * 64


def manifest():
    return CFBAuditManifest(
        sport="CFB",
        game_id="g1",
        market="SPREAD",
        selection="HOME",
        model_version="m1",
        feature_version="f1",
        calibrator_version="c1",
        simulation_version="s1",
        prior_version="p1",
        decay_schedule_hash=HEX,
        variance_model_version="v1",
        key_number_method="DISCRETE_EMPIRICAL_V1",
        data_cutoff="2026-08-29T12:00:00Z",
        feature_asof_ts="2026-08-29T11:00:00Z",
        odds_snapshot_id="o1",
        market_benchmark_id="b1",
        coverage_report_id="cov1",
        market_coverage_report_id="mcov1",
        book="DRAFTKINGS",
        line=-3.0,
        price=-110.0,
        quote_timestamp="2026-08-29T11:59:30Z",
        decision_timestamp="2026-08-29T12:00:00Z",
        model_p=0.56,
        no_vig_market_p=0.51,
        edge=0.05,
        ev=0.04,
        kelly=0.01,
        historical_gate_status="UNRUN",
        live_decision="BLOCKED",
        spec_sha=HEX,
        policy_sha=HEX,
        benchmark_methodology_sha=HEX,
        exposure_sha=HEX,
        market_context_sha=HEX,
        feature_source_policy_sha=HEX,
        quote_sync_policy_sha=HEX,
        model_promotion_policy_sha=HEX,
        entity_registry_sha=HEX,
        validation_attestation_sha=HEX,
        decision_provenance_sha=HEX,
    )


class CFBAuditManifestProvenanceTests(unittest.TestCase):
    def test_complete_manifest_is_replayable_identity_object(self):
        value = manifest().validate()
        self.assertEqual(len(value.content_hash()), 64)

    def test_bad_decision_provenance_hash_fails_closed(self):
        with self.assertRaisesRegex(CFBAuditContractError, "decision_provenance_sha:SHA256_REQUIRED"):
            replace(manifest(), decision_provenance_sha="missing").validate()


if __name__ == "__main__":
    unittest.main()
