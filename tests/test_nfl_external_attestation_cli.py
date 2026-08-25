import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.attest_nfl_forward_clv_and_build_registry import build_registry_from_bundles
from sportsedge.core.validation.nfl_forward_clv_attestation import canonical_clv_payload_sha256
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLExternalAttestationCLITests(unittest.TestCase):
    def _write_ci_bundle(self, root: Path, *, git_sha: str = "1" * 40):
        math = {
            "math_artifact": {
                "provenance": "REAL_PUBLIC_HISTORY",
                "source_sha256": "a" * 64,
                "code_git_sha": git_sha,
                "profile_version": "nfl-key-emergent-v3",
                "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
                "seasons": [2018, 2019, 2020, 2021, 2022, 2023],
                "key_numbers": [-7, -3, 3, 7],
                "per_key_abs_error": {"-7": 0.002, "-3": 0.003, "3": 0.002, "7": 0.004},
                "max_allowed_abs_error": 0.005,
            }
        }
        history = {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "a" * 64,
            "code_git_sha": git_sha,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "promotion_evidence": {
                "spread": {
                    "fold_wins": 7,
                    "fold_total": 10,
                    "fold_win_rate": 0.7,
                    "calibration": {"pass": True, "max_bin_deviation": 0.03, "threshold": 0.05},
                }
            },
        }
        registry = {
            "source_sha256": "a" * 64,
            "source_manifest_sha256": "a" * 64,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "ci_attestation_state": "UNATTESTED_IN_RUNNING_WORKFLOW",
        }
        source_manifest = {"manifest_sha256": "a" * 64}
        hashes = {}
        for name, payload in (
            ("nfl_simulator_profile.json", math),
            ("nfl_production_validation.json", history),
            ("nfl_promotion_registry.json", registry),
            ("nfl_source_manifest.json", source_manifest),
        ):
            path = root / name
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 2,
            "git_sha": git_sha,
            "source_manifest_sha256": "a" * 64,
            "ci_attestation_state": "PRE_CI_WORKFLOW_CANNOT_SELF_ATTEST",
            "artifacts": [{"path": name, "sha256": digest} for name, digest in sorted(hashes.items())],
        }
        (root / "nfl_promotion_evidence_manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )

    def _write_forward_bundle(self, root: Path, *, git_sha: str = "1" * 40):
        decision_hash = "c" * 64
        close_hash = "d" * 64
        decisions = root / "nfl_forward_decisions.jsonl"
        closes = root / "nfl_forward_closes.jsonl"
        decisions.write_bytes(b"decision-bytes\n")
        closes.write_bytes(b"close-bytes\n")
        decision_hash = hashlib.sha256(decisions.read_bytes()).hexdigest()
        close_hash = hashlib.sha256(closes.read_bytes()).hexdigest()
        clv = {
            "schema_version": 4,
            "sport": "nfl",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
            "decision_log_sha256": decision_hash,
            "close_log_sha256": close_hash,
            "decision_count": 200,
            "close_count": 200,
            "unique_observation_count": 200,
            "clv_probability_reference": "DECISION_THRESHOLD",
            "forward_time_contract": "PREGAME_DECISION_TO_PREGAME_CLOSE",
            "close_book_contract": "SAME_BOOK_AS_DECISION",
            "markets": {
                "spread": {
                    "logged_plays": 200,
                    "mean_clv": 0.005,
                    "clv_t_stat": 2.5,
                    "beat_close_rate": 0.56,
                }
            },
            "rejected_markets": {},
        }
        evidence = root / "nfl_clv_evidence.json"
        evidence.write_text(json.dumps(clv, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "collector_contract": "NFL_FORWARD_CLV_COLLECTION_V1",
            "git_sha": git_sha,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "artifacts": [
                {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in (decisions, closes, evidence)
            ],
        }
        (root / "nfl_forward_clv_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return clv

    def _surface(self, root: Path) -> Path:
        path = root / "surface.json"
        path.write_text(json.dumps({"sports": ["NFL"], "markets": [{"market": "spread"}]}), encoding="utf-8")
        return path

    def test_exact_same_head_two_run_attestation_can_build_final_registry(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            ci = base / "ci"; ci.mkdir()
            forward = base / "forward"; forward.mkdir()
            self._write_ci_bundle(ci)
            clv = self._write_forward_bundle(forward)
            result = build_registry_from_bundles(
                ci_bundle_dir=ci,
                ci_workflow_name="football-nfl-promotion-evidence",
                ci_workflow_conclusion="success",
                ci_workflow_head_sha="1" * 40,
                ci_workflow_run_id=111,
                forward_bundle_dir=forward,
                forward_workflow_name="football-nfl-forward-clv-collection",
                forward_workflow_conclusion="success",
                forward_workflow_event="schedule",
                forward_workflow_head_branch="main",
                forward_workflow_head_sha="1" * 40,
                forward_workflow_run_id=222,
                market_surface=self._surface(base),
            )
            self.assertEqual(result["markets"]["spread"]["stage"], "DEPLOYED")
            self.assertEqual(result["ci_attestation"]["workflow_run_id"], 111)
            self.assertEqual(result["clv_attestation"]["workflow_run_id"], 222)
            self.assertEqual(result["clv_attestation"]["clv_payload_sha256"], canonical_clv_payload_sha256(clv))

    def test_ci_and_forward_runs_must_share_exact_code_head(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            ci = base / "ci"; ci.mkdir()
            forward = base / "forward"; forward.mkdir()
            self._write_ci_bundle(ci, git_sha="1" * 40)
            self._write_forward_bundle(forward, git_sha="2" * 40)
            with self.assertRaisesRegex(ValueError, "NFL_EXTERNAL_ATTESTATION_CODE_SHA_MISMATCH"):
                build_registry_from_bundles(
                    ci_bundle_dir=ci,
                    ci_workflow_name="football-nfl-promotion-evidence",
                    ci_workflow_conclusion="success",
                    ci_workflow_head_sha="1" * 40,
                    ci_workflow_run_id=111,
                    forward_bundle_dir=forward,
                    forward_workflow_name="football-nfl-forward-clv-collection",
                    forward_workflow_conclusion="success",
                    forward_workflow_event="schedule",
                    forward_workflow_head_branch="main",
                    forward_workflow_head_sha="2" * 40,
                    forward_workflow_run_id=222,
                    market_surface=self._surface(base),
                )


if __name__ == "__main__":
    unittest.main()
