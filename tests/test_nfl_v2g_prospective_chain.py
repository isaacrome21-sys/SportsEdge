import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.sports.nfl.m2_v2g_forward import prediction_sha256

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_nfl_v2g_prospective_chain.py"
spec = importlib.util.spec_from_file_location("validate_nfl_v2g_prospective_chain", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NFLV2GProspectiveChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = self.root / "policy.json"
        self.pred = self.root / "pred.json"
        self.paper = self.root / "paper.json"
        artifact = "e7e591bf1ee7fbf6332cc6795aa1d7126fce9c6a43ac69c164b1f54433457977"
        implementation = "4dc37c4e445325c77737ec646fa37dbdbe3bfa6d"
        source_blob = "4d8a3e19033b70962bec6d93d46d92a58305778e"
        prereg = "c8381b09cdde2ccbddf6787127c838d114dee994"
        self.policy.write_text(json.dumps({
            "schema_version": mod.POLICY_SCHEMA,
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "frozen_research_artifact_sha256": artifact,
            "implementation_commit_sha": implementation,
            "candidate_source_git_blob_sha1": source_blob,
            "preregistration_commit_sha": prereg,
        }), encoding="utf-8")
        pred = {
            "schema_version": "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1",
            "status": "PROSPECTIVE_RESEARCH_PREDICTION_CAPTURED",
            "game_id": "2026_02_PIT_NE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "artifact_sha256": artifact,
            "implementation_commit_sha": implementation,
            "candidate_source_git_blob_sha1": source_blob,
            "preregistration_commit_sha": prereg,
            "kickoff_utc": "2026-09-20T17:00:00+00:00",
            "captured_at_utc": "2026-09-12T12:50:13+00:00",
            "market_prices_consumed": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "official_status_granted": False,
        }
        pred["prediction_sha256"] = prediction_sha256(pred)
        self.pred.write_text(json.dumps(pred, sort_keys=True), encoding="utf-8")
        paper = {
            "schema_version": mod.PAPER_SCHEMA,
            "status": "NO_PAPER_EDGE",
            "game_id": pred["game_id"],
            "candidate_id": pred["candidate_id"],
            "artifact_sha256": artifact,
            "prediction_sha256": pred["prediction_sha256"],
            "prediction_file_sha256": mod.sha256_file(self.pred),
            "policy_file_sha256": mod.sha256_file(self.policy),
            "market_prices_consumed_by_model": False,
            "staking_allowed": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "official_status_granted": False,
        }
        paper["paper_decision_sha256"] = mod.canonical_sha(paper, "paper_decision_sha256")
        self.paper.write_text(json.dumps(paper), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_chain_passes(self):
        result = mod.validate(self.pred, self.paper, self.policy)
        self.assertEqual("NFL_V2G_PROSPECTIVE_CHAIN_VALID", result["status"])
        self.assertFalse(result["binding_present"])

    def test_tampered_paper_fails(self):
        payload = json.loads(self.paper.read_text())
        payload["status"] = "PAPER_CANDIDATES_FROZEN"
        self.paper.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit) as ctx:
            mod.validate(self.pred, self.paper, self.policy)
        self.assertIn("NFL_V2G_CHAIN_PAPER_DECISION_SHA_MISMATCH", str(ctx.exception))

    def test_policy_drift_fails(self):
        payload = json.loads(self.policy.read_text())
        payload["extra"] = "drift"
        self.policy.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit) as ctx:
            mod.validate(self.pred, self.paper, self.policy)
        self.assertIn("NFL_V2G_CHAIN_POLICY_FILE_SHA_MISMATCH", str(ctx.exception))

    def test_wrong_implementation_identity_fails(self):
        payload = json.loads(self.pred.read_text())
        payload["implementation_commit_sha"] = "0" * 40
        payload["prediction_sha256"] = prediction_sha256(payload)
        self.pred.write_text(json.dumps(payload, sort_keys=True))
        paper = json.loads(self.paper.read_text())
        paper["prediction_sha256"] = payload["prediction_sha256"]
        paper["prediction_file_sha256"] = mod.sha256_file(self.pred)
        paper["paper_decision_sha256"] = mod.canonical_sha(paper, "paper_decision_sha256")
        self.paper.write_text(json.dumps(paper))
        with self.assertRaises(SystemExit) as ctx:
            mod.validate(self.pred, self.paper, self.policy)
        self.assertIn("NFL_V2G_CHAIN_POLICY_PROVENANCE_MISMATCH:implementation_commit_sha", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
