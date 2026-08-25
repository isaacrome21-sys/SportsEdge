import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sportsedge.core.validation.nfl_forward_clv_attestation import (
    canonical_clv_payload_sha256,
    verify_nfl_forward_clv_bundle,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLForwardCLVAttestationTests(unittest.TestCase):
    def _write_bundle(self, root: Path, *, git_sha: str = "1" * 40):
        decision = {
            "decision_ts": "2026-09-10T23:00:00+00:00",
            "game_start_ts": "2026-09-11T00:20:00+00:00",
            "game_id": "2026_01_AAA_BBB",
            "sport": "nfl",
            "market": "spread",
            "side": "AAA",
            "book": "draftkings",
            "line_at_decision": -3.0,
            "price_at_decision": -110,
            "model_prob": 0.56,
            "novig_prob": 0.50,
            "ev": 0.06,
            "kelly_frac": 0.02,
            "stake_units": 0.5,
            "gate_result": "OFFICIAL",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
        }
        close = {
            "close_ts": "2026-09-11T00:15:00+00:00",
            "game_start_ts": "2026-09-11T00:20:00+00:00",
            "game_id": "2026_01_AAA_BBB",
            "sport": "nfl",
            "market": "spread",
            "side": "AAA",
            "book": "draftkings",
            "closing_line": -3.5,
            "closing_price": -110,
            "closing_novig_prob": 0.52,
            "probability_line": -3.0,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
        }
        decisions = root / "nfl_forward_decisions.jsonl"
        closes = root / "nfl_forward_closes.jsonl"
        decisions.write_text(json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8")
        closes.write_text(json.dumps(close, sort_keys=True) + "\n", encoding="utf-8")
        decision_hash = hashlib.sha256(decisions.read_bytes()).hexdigest()
        close_hash = hashlib.sha256(closes.read_bytes()).hexdigest()
        evidence = {
            "schema_version": 4,
            "sport": "nfl",
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "code_git_sha": git_sha,
            "decision_log_sha256": decision_hash,
            "close_log_sha256": close_hash,
            "decision_count": 1,
            "close_count": 1,
            "unique_observation_count": 1,
            "first_decision_ts": decision["decision_ts"],
            "last_close_ts": close["close_ts"],
            "clv_probability_reference": "DECISION_THRESHOLD",
            "forward_time_contract": "PREGAME_DECISION_TO_PREGAME_CLOSE",
            "close_book_contract": "SAME_BOOK_AS_DECISION",
            "markets": {
                "spread": {
                    "logged_plays": 1,
                    "mean_clv": 0.02,
                    "beat_close_rate": 1.0,
                    "clv_t_stat": 0.0,
                }
            },
            "rejected_markets": {},
        }
        evidence_path = root / "nfl_clv_evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        files = [decisions, closes, evidence_path]
        manifest = {
            "schema_version": 1,
            "collector_contract": "NFL_FORWARD_CLV_COLLECTION_V1",
            "git_sha": git_sha,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "artifacts": [
                {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in files
            ],
        }
        (root / "nfl_forward_clv_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return evidence

    def _verify(self, root: Path, *, event="schedule", branch="main", sha="1" * 40):
        return verify_nfl_forward_clv_bundle(
            root,
            workflow_name="football-nfl-forward-clv-collection",
            workflow_conclusion="success",
            workflow_event=event,
            workflow_head_branch=branch,
            workflow_head_sha=sha,
            workflow_run_id=12345,
        )

    def test_scheduled_main_success_attests_exact_clv_bytes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = self._write_bundle(root)
            attestation = self._verify(root)
            self.assertEqual(attestation["git_sha"], "1" * 40)
            self.assertEqual(attestation["unique_observation_count"], 1)
            self.assertEqual(attestation["clv_payload_sha256"], canonical_clv_payload_sha256(evidence))
            self.assertEqual(attestation["workflow_event"], "schedule")
            self.assertEqual(attestation["workflow_head_branch"], "main")

    def test_manual_dispatch_cannot_be_promotion_attestation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_WORKFLOW_EVENT_INVALID"):
                self._verify(root, event="workflow_dispatch")

    def test_non_main_capture_cannot_be_promotion_attestation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_HEAD_BRANCH_INVALID"):
                self._verify(root, branch="feature/foo")

    def test_tampered_log_fails_manifest_hash(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root)
            with (root / "nfl_forward_closes.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_ARTIFACT_HASH_MISMATCH"):
                self._verify(root)

    def test_evidence_hashes_must_reproduce_exact_log_bytes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = self._write_bundle(root)
            evidence["decision_log_sha256"] = "f" * 64
            evidence_path = root / "nfl_clv_evidence.json"
            evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest_path = root / "nfl_forward_clv_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in manifest["artifacts"]:
                if row["path"] == evidence_path.name:
                    row["sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_DECISION_LOG_IDENTITY_MISMATCH"):
                self._verify(root)

    def test_workflow_head_must_match_bundle_code_sha(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bundle(root, git_sha="1" * 40)
            with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLV_HEAD_SHA_MISMATCH"):
                self._verify(root, sha="2" * 40)


if __name__ == "__main__":
    unittest.main()
