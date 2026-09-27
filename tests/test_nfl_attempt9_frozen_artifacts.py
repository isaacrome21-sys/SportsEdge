import json
import subprocess
import unittest
from hashlib import sha256
from pathlib import Path

from sportsedge.sports.nfl.attempt9_model_p import model_probability, verify_model_p_artifact

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "artifacts" / "football" / "nfl_attempt9_runtime_v1.json"
MODEL_P_PATH = ROOT / "artifacts" / "football" / "nfl_attempt9_model_p_v1.json"
SOURCES_PATH = ROOT / "config" / "public_training_sources_v1.json"

EXPECTED_RUNTIME_SHA = "effa86bea2b1e9043cf0f4adffa007910a3d59f979f3ae07bcac15c6c4712d10"
EXPECTED_MODEL_P_SHA = "868d02e16443969407cd15494c1429a4e664f38847e8e2f1366f5a66708ec92e"
EXPECTED_SOURCE_SHA = "59c8bea7e185dde9e6053a06c24c34f6e5a91dcaea3187c0d9bab12759bb05fb"
EXPECTED_BLOBS = {
    "config/public_training_sources_v1.json": "3ef8ea2a16542b63b2833f2e05977e86ed8c2f2b",
    "scripts/build_nfl_attempt9_runtime_artifact.py": "113e887da78c0cfde199d71606626ee72baca9da",
    "scripts/build_nfl_attempt9_model_p_artifact.py": "9032e1d8c65a96fdca85e46bf9c57f2d34b7d9b1",
    "sportsedge/sports/nfl/attempt9_model_p.py": "b89b76b064ed863c6b78e6de7ca3838d7a6334bc",
}


def canonical_artifact_sha(payload: dict) -> str:
    body = dict(payload)
    body.pop("artifact_sha256", None)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(raw).hexdigest()


class NFLAttempt9FrozenArtifactTests(unittest.TestCase):
    def setUp(self):
        self.runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        self.model_p = json.loads(MODEL_P_PATH.read_text(encoding="utf-8"))
        self.sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    def test_runtime_is_exact_known_good_hosted_artifact(self):
        self.assertEqual(self.runtime["artifact_sha256"], EXPECTED_RUNTIME_SHA)
        self.assertEqual(canonical_artifact_sha(self.runtime), EXPECTED_RUNTIME_SHA)
        self.assertEqual(self.runtime["source"]["sha256"], EXPECTED_SOURCE_SHA)
        self.assertEqual(self.runtime["candidate"]["selected_attempt"], 9)
        self.assertEqual(self.runtime["candidate"]["decay"], 0.85)
        for key in ("creates_model_p", "promotion_authority", "truth_gate_pass", "official_authority", "staking_authority"):
            self.assertIs(self.runtime["authority"][key], False)

    def test_model_p_artifact_is_bound_to_runtime_and_remains_nonpromoted(self):
        self.assertEqual(verify_model_p_artifact(self.model_p), EXPECTED_MODEL_P_SHA)
        self.assertEqual(self.model_p["runtime_artifact_sha256"], EXPECTED_RUNTIME_SHA)
        self.assertEqual(self.model_p["source_sha256"], EXPECTED_SOURCE_SHA)
        self.assertIs(self.model_p["authority"]["creates_model_p"], True)
        for key in ("historical_fit_promotion_authority", "deployed", "truth_gate_pass", "official_authority", "staking_authority"):
            self.assertIs(self.model_p["authority"][key], False)
        self.assertIs(self.model_p["prospective_evidence"]["backfill_allowed"], False)
        self.assertIs(self.model_p["prospective_evidence"]["historical_fit_counts_as_promotion_evidence"], False)

    def test_pinned_public_source_identity_matches_frozen_artifacts(self):
        source = self.sources["sources"]["nfl_attempt9"]
        self.assertEqual(source["expected_sha256"], EXPECTED_SOURCE_SHA)
        self.assertEqual(source["actions_run_id"], self.runtime["frozen_selection_provenance"]["actions_run_id"])
        self.assertEqual(source["actions_artifact_id"], self.runtime["frozen_selection_provenance"]["actions_artifact_id"])
        self.assertEqual(source["actions_artifact_digest"], self.runtime["frozen_selection_provenance"]["actions_artifact_digest"])

    def test_frozen_code_blob_bindings_have_not_drifted(self):
        for path, expected in EXPECTED_BLOBS.items():
            actual = subprocess.check_output(["git", "hash-object", path], cwd=ROOT, text=True).strip()
            self.assertEqual(actual, expected, path)

    def test_frozen_artifact_serves_shadow_probability_without_authority_leak(self):
        out = model_probability(
            self.model_p,
            market="spread",
            raw_prediction=4.0,
            line=-3.5,
            selection="home",
        )
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)
        self.assertIs(out["promotion_authority"], False)
        self.assertIs(out["deployed"], False)
        self.assertIs(out["truth_gate_pass"], False)
        self.assertIs(out["official_authority"], False)
        self.assertIs(out["staking_authority"], False)


if __name__ == "__main__":
    unittest.main()
