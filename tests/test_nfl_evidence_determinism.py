from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.core.validation.evidence_determinism import (
    canonical_json_bytes,
    compare_evidence_directories,
)


_GIT_SHA = "1" * 40
_SOURCE_SHA = "a" * 64


class EvidenceDeterminismTests(unittest.TestCase):
    def _write(self, root: Path, name: str, payload) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _write_bytes(self, root: Path, name: str, payload: bytes) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def _identity(self, *, sport: str = "nfl", git_sha: str = _GIT_SHA, source_sha: str = _SOURCE_SHA):
        return {
            "sport": sport,
            "code_git_sha": git_sha,
            "source_manifest_sha256": source_sha,
            "folds": [
                {"season": 2023, "market": "spread", "m2_log_loss": 0.61},
                {"season": 2024, "market": "spread", "m2_log_loss": 0.59},
            ],
        }

    def _compare(
        self,
        baseline: Path,
        candidate: Path,
        *,
        sport: str = "nfl",
        expected_git_sha: str = _GIT_SHA,
        determinism_class: str = "SAME_ENV_SAME_SHA",
        replay_scope: str | None = None,
    ):
        scope = replay_scope or (
            "TRAINING_BUNDLE_TO_ARTIFACT" if sport == "cfb" else "FROZEN_SOURCE_MANIFEST_TO_ARTIFACT"
        )
        return compare_evidence_directories(
            sport=sport,
            baseline_dir=baseline,
            candidate_dir=candidate,
            artifacts=["evidence.json", "model.json"],
            identity_artifact="evidence.json",
            expected_git_sha=expected_git_sha,
            determinism_class=determinism_class,
            replay_scope=scope,
            baseline_label="CI_ATTEMPT_001",
            candidate_label="CI_REPLAY_001",
        )

    def test_canonical_json_ignores_mapping_order_only_for_diagnostics(self):
        self.assertEqual(
            canonical_json_bytes({"b": 2, "a": [1, 2]}),
            canonical_json_bytes({"a": [1, 2], "b": 2}),
        )
        self.assertNotEqual(
            canonical_json_bytes({"a": [1, 2]}),
            canonical_json_bytes({"a": [2, 1]}),
        )

    def test_byte_identical_replay_passes_without_semantic_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            identity_bytes = (json.dumps(self._identity(), indent=2) + "\n").encode("utf-8")
            model_bytes = (json.dumps({"coef": [1.0, 2.0]}, indent=2) + "\n").encode("utf-8")
            for directory in (baseline, candidate):
                self._write_bytes(directory, "evidence.json", identity_bytes)
                self._write_bytes(directory, "model.json", model_bytes)

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["gate_basis"], "BYTE_IDENTITY")
            self.assertTrue(report["all_bytes_equal"])
            self.assertEqual(report["determinism_class"], "SAME_ENV_SAME_SHA")
            self.assertEqual(report["replay_scope"], "FROZEN_SOURCE_MANIFEST_TO_ARTIFACT")
            self.assertTrue(all(row["byte_equal"] for row in report["artifact_comparisons"]))
            self.assertTrue(all(row["semantic_diagnostic"] is None for row in report["artifact_comparisons"]))

    def test_semantically_equal_but_byte_different_replay_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            identity = self._identity()
            model = {"weights": {"away": -0.2, "home": 0.3}, "train_seasons": [2021, 2022, 2023]}
            self._write(baseline, "evidence.json", identity)
            self._write(candidate, "evidence.json", {key: identity[key] for key in reversed(identity)})
            self._write(baseline, "model.json", model)
            self._write(candidate, "model.json", {"train_seasons": [2021, 2022, 2023], "weights": {"home": 0.3, "away": -0.2}})

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["reason"], "BYTE_OUTPUT_MISMATCH_AT_IDENTICAL_CODE_AND_SOURCE_IDENTITY")
            self.assertFalse(report["all_bytes_equal"])
            mismatches = [row for row in report["artifact_comparisons"] if not row["byte_equal"]]
            self.assertTrue(mismatches)
            self.assertTrue(all(row["semantic_diagnostic"]["semantic_equal"] for row in mismatches))

    def test_changed_fold_outcome_fails_with_semantic_pointer_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            left = self._identity()
            right = self._identity()
            right["folds"][1]["m2_log_loss"] = 0.60
            self._write(baseline, "evidence.json", left)
            self._write(candidate, "evidence.json", right)
            same_model = (json.dumps({"coef": [1.0, 2.0]}, indent=2) + "\n").encode("utf-8")
            self._write_bytes(baseline, "model.json", same_model)
            self._write_bytes(candidate, "model.json", same_model)

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["failure_class"], "NON_DETERMINISTIC_EVIDENCE")
            self.assertIn("/folds/1/m2_log_loss", {row["path"] for row in report["differences"]})
            evidence = next(row for row in report["artifact_comparisons"] if row["artifact"] == "evidence.json")
            self.assertFalse(evidence["byte_equal"])
            self.assertFalse(evidence["semantic_diagnostic"]["semantic_equal"])

    def test_expected_git_sha_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            for directory in (baseline, candidate):
                self._write(directory, "evidence.json", self._identity())
                self._write(directory, "model.json", {"coef": [1.0]})

            report = self._compare(baseline, candidate, expected_git_sha="2" * 40)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["failure_class"], "IDENTITY_MISMATCH")
            self.assertTrue(report["reason"].startswith("BASELINE_CODE_GIT_SHA_MISMATCH:"))

    def test_source_manifest_mismatch_blocks_before_output_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            self._write(baseline, "evidence.json", self._identity(source_sha="a" * 64))
            self._write(candidate, "evidence.json", self._identity(source_sha="b" * 64))
            self._write(baseline, "model.json", {"coef": [1.0]})
            self._write(candidate, "model.json", {"coef": [9.0]})

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["failure_class"], "SOURCE_IDENTITY_MISMATCH")
            self.assertEqual(report["reason"], "SOURCE_MANIFEST_SHA256_MISMATCH")

    def test_missing_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            self._write(baseline, "evidence.json", self._identity())
            self._write(candidate, "evidence.json", self._identity())
            self._write(baseline, "model.json", {"coef": [1.0]})

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["failure_class"], "MISSING_EVIDENCE")
            self.assertEqual(report["reason"], "CANDIDATE_ARTIFACT_MISSING:model.json")

    def test_same_byte_gate_contract_accepts_mlb_cfb_and_nfl(self):
        for sport in ("mlb", "cfb", "nfl"):
            with self.subTest(sport=sport), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                baseline = root / "baseline"
                candidate = root / "candidate"
                identity_bytes = (json.dumps(self._identity(sport=sport), indent=2) + "\n").encode("utf-8")
                model_bytes = (json.dumps({"coef": [1.0]}, indent=2) + "\n").encode("utf-8")
                for directory in (baseline, candidate):
                    self._write_bytes(directory, "evidence.json", identity_bytes)
                    self._write_bytes(directory, "model.json", model_bytes)
                report = self._compare(baseline, candidate, sport=sport)
                self.assertEqual(report["status"], "PASS")
                if sport == "cfb":
                    self.assertEqual(report["replay_scope"], "TRAINING_BUNDLE_TO_ARTIFACT")

    def test_missing_source_manifest_blocks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            identity = {"sport": "nfl", "code_git_sha": _GIT_SHA, "folds": []}
            for directory in (baseline, candidate):
                self._write(directory, "evidence.json", identity)
                self._write(directory, "model.json", {"coef": [1.0]})

            report = self._compare(baseline, candidate)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["failure_class"], "SOURCE_IDENTITY_MISSING")

    def test_missing_certification_labels_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "baseline"
            candidate = root / "candidate"
            for directory in (baseline, candidate):
                self._write(directory, "evidence.json", self._identity())
                self._write(directory, "model.json", {"coef": [1.0]})

            report = self._compare(baseline, candidate, determinism_class="")
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["reason"], "DETERMINISM_CLASS_REQUIRED")


if __name__ == "__main__":
    unittest.main()
