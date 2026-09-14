import unittest
from pathlib import Path


WORKFLOW = Path('.github/workflows/nfl-market-maker-radar-capture.yml')


class NFLMarketMakerRadarWorkflowTests(unittest.TestCase):
    def test_repo_importing_radar_scripts_run_as_modules(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('python -m scripts.analyze_market_maker_radar_v2', text)
        self.assertIn('python -m scripts.recheck_market_maker_candidate_persistence', text)
        self.assertIn('python -m scripts.settle_market_maker_candidate_ledger_v2', text)
        self.assertNotIn('python scripts/analyze_market_maker_radar_v2.py', text)
        self.assertNotIn('python scripts/recheck_market_maker_candidate_persistence.py', text)
        self.assertNotIn('python scripts/settle_market_maker_candidate_ledger_v2.py', text)

    def test_workflow_anchors_takeability_offset_to_capture_time(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn("capture['captured_at']", text)
        self.assertIn("policy['takeability']['persistence_recheck_offset_seconds']", text)
        self.assertIn('target = captured_at + timedelta(seconds=offset)', text)
        self.assertNotIn('sleep 30', text)

    def test_workflow_enforces_roi_first_semantics(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('REALIZED_ROI_ON_FILLED_WAGERS', text)
        self.assertIn('DETECTOR_PROCESS_CHECK_NOT_EDGE_VALIDATION', text)
        self.assertIn('new_persistence_count', text)
        self.assertIn('counts_as_independent_context_class == false', text)


if __name__ == '__main__':
    unittest.main()
