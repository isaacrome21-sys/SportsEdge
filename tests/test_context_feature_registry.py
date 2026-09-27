from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestContextFeatureRegistry(unittest.TestCase):
    def test_handles_and_odds_cannot_enter_model_p(self):
        raw = json.loads((ROOT / "config/context_feature_registry_v1.json").read_text())
        self.assertTrue(raw["market_blind"])
        self.assertFalse(raw["features"]["ticket_handles_splits_steam"]["model_p"])
        self.assertTrue(raw["features"]["ticket_handles_splits_steam"]["never_model_p"])
        self.assertTrue(raw["features"]["odds_lines_juice"]["never_model_p"])
        self.assertFalse(raw["authority"]["official_authority"])


if __name__ == "__main__":
    unittest.main()
