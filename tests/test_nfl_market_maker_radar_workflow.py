import unittest
from pathlib import Path


WORKFLOW = Path('.github/workflows/nfl-market-maker-radar-capture.yml')


class NFLMarketMakerRadarWorkflowTests(unittest.TestCase):
    def test_repo_importing_v2_scripts_run_as_modules(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('python -m scripts.analyze_market_maker_radar_v2', text)
        self.assertIn('python -m scripts.settle_market_maker_candidate_ledger', text)
        self.assertNotIn('python scripts/analyze_market_maker_radar_v2.py', text)
        self.assertNotIn('python scripts/settle_market_maker_candidate_ledger.py', text)


if __name__ == '__main__':
    unittest.main()
