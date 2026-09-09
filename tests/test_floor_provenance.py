from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from sportsedge.floor_provenance import (
    FloorProvenanceError,
    verify_floor_config_provenance,
    verify_floor_provenance,
)


def _run(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _commit(root: Path, message: str) -> str:
    _run(root, "add", "-A")
    _run(root, "commit", "-m", message)
    return _run(root, "rev-parse", "HEAD")


class ProvenanceRepo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _run(self.root, "init")
        _run(self.root, "config", "user.name", "SportsEdge Test")
        _run(self.root, "config", "user.email", "sportsedge-test@example.invalid")

        self.manifest_path = "evidence/pre_analysis_manifest.json"
        self.code_path = "scripts/floor_derivation.py"
        self.evidence_path = "evidence/floor_result.json"

        manifest = b'{"selection":"precommitted","version":1}\n'
        code = b'def derive(rows):\n    return rows\n'
        self._write(self.manifest_path, manifest)
        self._write(self.code_path, code)
        self.manifest_commit = _commit(self.root, "freeze manifest and derivation code")
        self.manifest_sha = _sha(manifest)
        self.code_commit = self.manifest_commit
        self.code_sha = _sha(code)

        # Deliberately edit the manifest after its recorded commit.  Verification
        # must reconstruct the historical bytes, not hash this later working-tree
        # version or the file as it exists in the evidence commit.
        self._write(self.manifest_path, b'{"selection":"later-edit","version":2}\n')
        evidence = b'{"result":"held-out-evidence","rows":17}\n'
        self._write(self.evidence_path, evidence)
        self.evidence_commit = _commit(self.root, "record held-out evidence")
        self.evidence_sha = _sha(evidence)

        self._write("evidence/floor_freeze_marker.txt", b"floor freeze follows evidence\n")
        self.floor_commit = _commit(self.root, "freeze floor record")

        self.config = {
            "truth_gate": {
                "schema_version": 2,
                "production": {
                    "fail_closed": True,
                    "allow_cli_floor_override": False,
                    "require_frozen_floor_for_eligible_market": True,
                },
                "devig_policy": {
                    "policy_id": "EDGE_FLOOR_DEVIG_V1",
                    "status": "FROZEN_PRE_DERIVATION",
                    "longshot_trigger_american_odds": 400,
                    "longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
                    "sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],
                    "sensitivity_limit_absolute_probability_points": 0.01,
                    "stable_candidate_estimator": "MULTIPLICATIVE_V1",
                    "longshot_candidate_estimator": "POWER_V1",
                    "haircut_probability_points": 0.0,
                    "aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
                    "sensitivity_failure": "BLOCK",
                },
                "edge_floors": {
                    "MLB_MONEYLINE": {
                        "status": "FROZEN",
                        "value_probability_points": 0.02,
                        "method_version": "test_only_floor_derivation_v1",
                        "evidence": {
                            "manifest_path": self.manifest_path,
                            "manifest_commit": self.manifest_commit,
                            "manifest_sha256": self.manifest_sha,
                            "evidence_path": self.evidence_path,
                            "evidence_commit": self.evidence_commit,
                            "evidence_sha256": self.evidence_sha,
                            "derivation_code_path": self.code_path,
                            "derivation_code_commit": self.code_commit,
                            "derivation_code_sha256": self.code_sha,
                            "oos_cutoff_utc": "2026-08-31T23:59:59Z",
                        },
                        "frozen": {"frozen_by_commit": self.floor_commit},
                    }
                },
            }
        }

    def _write(self, rel: str, raw: bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def close(self):
        self.tmp.cleanup()


class FloorProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.repo = ProvenanceRepo()

    def tearDown(self):
        self.repo.close()

    def test_valid_bundle_uses_historical_manifest_evidence_and_code_bytes(self):
        verified = verify_floor_provenance(
            market="MLB_MONEYLINE",
            config=self.repo.config,
            repo_root=self.repo.root,
        )
        self.assertEqual(verified.manifest_commit, self.repo.manifest_commit)
        self.assertEqual(verified.evidence_commit, self.repo.evidence_commit)
        self.assertEqual(verified.floor_commit, self.repo.floor_commit)
        self.assertEqual(verified.manifest_sha256, self.repo.manifest_sha)

    def test_manifest_sha256_mutation_fails_its_own_check(self):
        cfg = deepcopy(self.repo.config)
        cfg["truth_gate"]["edge_floors"]["MLB_MONEYLINE"]["evidence"]["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            FloorProvenanceError, "^PROVENANCE_INVALID:MANIFEST_SHA256_MISMATCH$"
        ):
            verify_floor_provenance(
                market="MLB_MONEYLINE", config=cfg, repo_root=self.repo.root
            )

    def test_evidence_sha256_mutation_fails_its_own_check(self):
        cfg = deepcopy(self.repo.config)
        cfg["truth_gate"]["edge_floors"]["MLB_MONEYLINE"]["evidence"]["evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            FloorProvenanceError, "^PROVENANCE_INVALID:EVIDENCE_SHA256_MISMATCH$"
        ):
            verify_floor_provenance(
                market="MLB_MONEYLINE", config=cfg, repo_root=self.repo.root
            )

    def test_derivation_code_sha256_mutation_fails_its_own_check(self):
        cfg = deepcopy(self.repo.config)
        cfg["truth_gate"]["edge_floors"]["MLB_MONEYLINE"]["evidence"]["derivation_code_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            FloorProvenanceError,
            "^PROVENANCE_INVALID:DERIVATION_CODE_SHA256_MISMATCH$",
        ):
            verify_floor_provenance(
                market="MLB_MONEYLINE", config=cfg, repo_root=self.repo.root
            )

    def test_unavailable_commit_is_unresolvable_not_invalid(self):
        cfg = deepcopy(self.repo.config)
        cfg["truth_gate"]["edge_floors"]["MLB_MONEYLINE"]["evidence"]["evidence_commit"] = "f" * 40
        with self.assertRaisesRegex(
            FloorProvenanceError,
            "^PROVENANCE_UNRESOLVABLE:MANIFEST_BEFORE_EVIDENCE_DESCENDANT_COMMIT_NOT_AVAILABLE$",
        ):
            verify_floor_provenance(
                market="MLB_MONEYLINE", config=cfg, repo_root=self.repo.root
            )

    def test_manifest_and_evidence_same_commit_is_invalid_chronology(self):
        cfg = deepcopy(self.repo.config)
        evidence = cfg["truth_gate"]["edge_floors"]["MLB_MONEYLINE"]["evidence"]
        evidence["evidence_commit"] = self.repo.manifest_commit
        with self.assertRaisesRegex(
            FloorProvenanceError,
            "^PROVENANCE_INVALID:MANIFEST_BEFORE_EVIDENCE_NOT_STRICT$",
        ):
            verify_floor_provenance(
                market="MLB_MONEYLINE", config=cfg, repo_root=self.repo.root
            )

    def test_config_verifier_accepts_zero_frozen_floors_without_promotion(self):
        import json
        cfg = deepcopy(self.repo.config)
        cfg["truth_gate"]["edge_floors"] = {}
        path = self.repo.root / "zero_floors.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        self.assertEqual(
            verify_floor_config_provenance(config_path=path, repo_root=self.repo.root), []
        )


if __name__ == "__main__":
    unittest.main()
