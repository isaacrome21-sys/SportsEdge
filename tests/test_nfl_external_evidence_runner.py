import unittest
from pathlib import Path


class NFLExternalEvidenceRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("scripts/run_nfl_external_evidence.sh").read_text()

    def test_exact_sha_and_clean_tree_are_required(self):
        self.assertIn("NFL_EXTERNAL_EVIDENCE_SHA_MISMATCH", self.text)
        self.assertIn("NFL_EXTERNAL_EVIDENCE_DIRTY_TREE", self.text)
        self.assertIn("git rev-parse HEAD", self.text)

    def test_main_is_required_by_default(self):
        self.assertIn("NFL_EXTERNAL_EVIDENCE_MAIN_REQUIRED", self.text)
        self.assertIn("ALLOW_NON_MAIN_EXTERNAL_EVIDENCE", self.text)

    def test_external_lane_cannot_claim_ci_attestation(self):
        self.assertIn('"ci_attestation_state": "EXTERNAL_RUNNER_UNATTESTED"', self.text)
        self.assertIn('"promotion_allowed": False', self.text)
        self.assertIn("EXTERNAL_RUNNER_CANNOT_CREATE_DEPLOYED_STATE", self.text)
        self.assertNotIn("scripts/attest_nfl_ci_and_build_registry.py \\", self.text)

    def test_runner_uses_same_historical_source_window_and_manifest_binding(self):
        self.assertIn("--start-season 2016 --end-season 2025", self.text)
        self.assertIn("--neutral-site-policy exclude_from_evaluation", self.text)
        self.assertIn("nfl_source_manifest.json", self.text)
        self.assertIn("NFL_EVIDENCE_MANIFEST_BINDING_MISMATCH", self.text)
        self.assertIn("NFL_EVIDENCE_CODE_SHA_MISMATCH", self.text)

    def test_runner_executes_both_contract_test_surfaces_before_history(self):
        football = self.text.index("test_football*.py")
        nfl = self.text.index("test_nfl*.py")
        download = self.text.index("games.csv")
        self.assertLess(football, download)
        self.assertLess(nfl, download)


if __name__ == "__main__":
    unittest.main()
