from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestCFBPaperMarketContract(unittest.TestCase):
    def test_paper_lane_is_explicitly_non_model_and_non_official(self):
        s=(ROOT/"scripts/run_cfb_paper_market.py").read_text()
        self.assertIn('"status":"PAPER_ONLY"',s)
        self.assertIn('"model_p":None',s)
        self.assertIn('"official":False',s)
        self.assertNotIn("OFFICIAL_BET",s)
        w=(ROOT/".github/workflows/cfb-paper-market-card.yml").read_text()
        self.assertIn("Assert zero betting authority",w)
        self.assertIn("not any(p['authority'].values())",w)
if __name__=="__main__": unittest.main()
