import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.attest_nfl_forward_clv_and_build_registry import build_registry_from_bundles
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLExternalAttestationCLITests(unittest.TestCase):
    SHA = "1" * 40

    def _ci_bundle(self, root: Path):
        math = {"math_artifact": {"provenance": "REAL_PUBLIC_HISTORY", "source_sha256": "a" * 64,
                "code_git_sha": self.SHA, "profile_version": "nfl-key-emergent-v3",
                "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1", "seasons": [2018, 2019],
                "key_numbers": [-7, -3, 3, 7], "per_key_abs_error": {"-7": .002, "-3": .002, "3": .002, "7": .002},
                "max_allowed_abs_error": .005}}
        history = {"provenance": "REAL_PUBLIC_HISTORY", "source_sha256": "a" * 64,
                   "source_manifest_sha256": "a" * 64, "code_git_sha": self.SHA,
                   "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
                   "promotion_evidence": {"spread": {"fold_wins": 7, "fold_total": 10,
                   "calibration": {"pass": True, "max_bin_deviation": .03, "threshold": .05}}}}
        registry = {"source_sha256": "a" * 64, "source_manifest_sha256": "a" * 64,
                    "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT,
                    "ci_attestation_state": "UNATTESTED_IN_RUNNING_WORKFLOW"}
        source = {"manifest_sha256": "a" * 64}
        hashes = {}
        for name, payload in (("nfl_simulator_profile.json", math), ("nfl_production_validation.json", history),
                              ("nfl_promotion_registry.json", registry), ("nfl_source_manifest.json", source)):
            p = root / name; p.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        manifest = {"schema_version": 2, "git_sha": self.SHA, "source_manifest_sha256": "a" * 64,
                    "ci_attestation_state": "PRE_CI_WORKFLOW_CANNOT_SELF_ATTEST",
                    "artifacts": [{"path": n, "sha256": h} for n, h in sorted(hashes.items())]}
        (root / "nfl_promotion_evidence_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _forward_bundle(self, root: Path):
        identity = {"game_id": "2026_01_AAA_BBB", "sport": "nfl", "market": "spread", "side": "AAA",
                    "book": "draftkings", "model_id": PRODUCTION_NFL_M2_MODEL_ID,
                    "feature_contract": NFL_M2_FEATURE_CONTRACT, "code_git_sha": self.SHA}
        decision = dict(identity, decision_ts="2026-09-10T23:00:00+00:00", game_start_ts="2026-09-11T00:20:00+00:00",
                        line_at_decision=-3.0, price_at_decision=-110, model_prob=.56, novig_prob=.50,
                        ev=.06, kelly_frac=.02, stake_units=.5, gate_result="OFFICIAL")
        close = dict(identity, close_ts="2026-09-11T00:15:00+00:00", game_start_ts="2026-09-11T00:20:00+00:00",
                     closing_line=-3.5, closing_price=-110, closing_novig_prob=.52, probability_line=-3.0)
        d = root / "nfl_forward_decisions.jsonl"; d.write_text(json.dumps(decision) + "\n", encoding="utf-8")
        c = root / "nfl_forward_closes.jsonl"; c.write_text(json.dumps(close) + "\n", encoding="utf-8")
        evidence = {"schema_version": 4, "sport": "nfl", "model_id": PRODUCTION_NFL_M2_MODEL_ID,
                    "feature_contract": NFL_M2_FEATURE_CONTRACT, "code_git_sha": self.SHA,
                    "decision_log_sha256": hashlib.sha256(d.read_bytes()).hexdigest(),
                    "close_log_sha256": hashlib.sha256(c.read_bytes()).hexdigest(),
                    "decision_count": 1, "close_count": 1, "unique_observation_count": 1,
                    "clv_probability_reference": "DECISION_THRESHOLD",
                    "forward_time_contract": "PREGAME_DECISION_TO_PREGAME_CLOSE",
                    "close_book_contract": "SAME_BOOK_AS_DECISION",
                    "markets": {"spread": {"logged_plays": 1, "mean_clv": .02, "clv_t_stat": 0.0, "beat_close_rate": 1.0}},
                    "rejected_markets": {}}
        e = root / "nfl_clv_evidence.json"; e.write_text(json.dumps(evidence), encoding="utf-8")
        manifest = {"schema_version": 1, "collector_contract": "NFL_FORWARD_CLV_COLLECTION_V1",
                    "git_sha": self.SHA, "model_id": PRODUCTION_NFL_M2_MODEL_ID,
                    "feature_contract": NFL_M2_FEATURE_CONTRACT,
                    "artifacts": [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (d, c, e)]}
        (root / "nfl_forward_clv_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _surface(self, root: Path):
        p = root / "surface.json"; p.write_text(json.dumps({"sports": ["NFL"], "markets": [{"market": "spread"}]}), encoding="utf-8")
        return p

    def test_two_exact_head_bundles_build_externally_attested_registry(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp); ci = base / "ci"; forward = base / "forward"; ci.mkdir(); forward.mkdir()
            self._ci_bundle(ci); self._forward_bundle(forward)
            registry = build_registry_from_bundles(
                ci_bundle_dir=ci, ci_workflow_name="football-nfl-promotion-evidence", ci_workflow_conclusion="success",
                ci_workflow_head_sha=self.SHA, ci_workflow_run_id=111,
                forward_bundle_dir=forward, forward_workflow_name="football-nfl-forward-clv-collection",
                forward_workflow_conclusion="success", forward_workflow_event="schedule", forward_workflow_head_branch="main",
                forward_workflow_head_sha=self.SHA, forward_workflow_run_id=222, market_surface=self._surface(base))
            self.assertEqual(registry["clv_attestation_state"], "EXTERNALLY_ATTESTED")
            self.assertEqual(registry["markets"]["spread"]["stage"], "CI_ATTESTED")
            self.assertEqual(registry["clv_attestation"]["workflow_run_id"], 222)

    def test_two_workflows_must_bind_same_exact_head(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp); ci = base / "ci"; forward = base / "forward"; ci.mkdir(); forward.mkdir()
            self._ci_bundle(ci); self._forward_bundle(forward)
            with self.assertRaisesRegex(ValueError, "NFL_EXTERNAL_ATTESTATION_CODE_SHA_MISMATCH"):
                build_registry_from_bundles(
                    ci_bundle_dir=ci, ci_workflow_name="football-nfl-promotion-evidence", ci_workflow_conclusion="success",
                    ci_workflow_head_sha=self.SHA, ci_workflow_run_id=111,
                    forward_bundle_dir=forward, forward_workflow_name="football-nfl-forward-clv-collection",
                    forward_workflow_conclusion="success", forward_workflow_event="schedule", forward_workflow_head_branch="main",
                    forward_workflow_head_sha="2" * 40, forward_workflow_run_id=222, market_surface=self._surface(base))


if __name__ == "__main__":
    unittest.main()
