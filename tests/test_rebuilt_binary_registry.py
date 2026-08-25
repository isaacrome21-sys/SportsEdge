import json
import unittest
from pathlib import Path


class RebuiltBinaryRegistryTests(unittest.TestCase):
    def test_rebuilt_markets_are_candidates_not_promoted(self):
        deployments = json.loads(Path("config/deployments.json").read_text())["markets"]
        evidence = json.loads(Path("config/mlb_validation_evidence.json").read_text())["markets"]
        behavior = json.loads(Path("config/mlb_behavioral_disposition.json").read_text())["markets"]

        self.assertEqual(deployments["FIRST_HOME_RUN"]["stage"], "ORDERING_AWARE_CANDIDATE")
        self.assertEqual(deployments["PITCHER_RECORD_WIN"]["stage"], "WIN_CREDIT_STATE_CANDIDATE")
        for market in ("FIRST_HOME_RUN", "PITCHER_RECORD_WIN"):
            self.assertFalse(deployments[market]["eligible"])
            self.assertEqual(evidence[market]["evidence_count"], 0)
            self.assertEqual(evidence[market]["evidence_status"], "UNRUN")
            self.assertIn("IMPLEMENTED", behavior[market]["remediation_state"])
            self.assertIn("REVALIDATION_REQUIRED", behavior[market]["remediation_state"])


if __name__ == "__main__":
    unittest.main()
