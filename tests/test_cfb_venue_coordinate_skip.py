from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestPaperPolicyStaysNonOfficial(unittest.TestCase):
    def test_paper_policy_forbids_official_authority(self):
        policy = json.loads((ROOT / "config/paper_output_policy_v1.json").read_text())
        self.assertEqual(policy["schema"], "PAPER_OUTPUT_POLICY_V1")
        self.assertIs(policy["governance"]["official_authority"], False)
        self.assertIs(policy["governance"]["paper_cannot_promote_itself"], True)
        self.assertNotIn("OFFICIAL", policy["labels"]["output_class"])


if __name__ == "__main__":
    unittest.main()
