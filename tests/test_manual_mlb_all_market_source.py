import unittest
from pathlib import Path

from sportsedge import manual_mlb_snapshot
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource


class ManualMlbAllMarketSourceTests(unittest.TestCase):
    def test_manual_snapshot_is_bound_to_all_market_history_source(self):
        self.assertIs(manual_mlb_snapshot.MLBAllMarketHistorySource, MLBAllMarketHistorySource)
        text = Path("sportsedge/manual_mlb_snapshot.py").read_text(encoding="utf-8")
        self.assertIn("hist = MLBAllMarketHistorySource(", text)
        self.assertNotIn("MLBGenericHistorySource", text)


if __name__ == "__main__":
    unittest.main()
