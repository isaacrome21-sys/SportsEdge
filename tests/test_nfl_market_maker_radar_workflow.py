import unittest
from pathlib import Path

WORKFLOW = Path('.github/workflows/nfl-market-maker-radar-capture.yml')


class NFLMarketMakerRadarWorkflowTests(unittest.TestCase):
    def test_repo_importing_radar_scripts_run_as_modules(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('python -m scripts.analyze_market_maker_radar_v2', text)
        self.assertIn('python -m scripts.recheck_market_maker_candidate_persistence', text)
        self.assertIn('python -m scripts.evaluate_market_maker_execution_pilot', text)
        self.assertIn('python -m scripts.settle_market_maker_candidate_ledger_v2', text)
        self.assertNotIn('python scripts/analyze_market_maker_radar_v2.py', text)
        self.assertNotIn('python scripts/recheck_market_maker_candidate_persistence.py', text)

    def test_workflow_anchors_both_takeability_offsets_to_capture_time(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertGreaterEqual(text.count("capture['captured_at']"), 2)
        self.assertIn('timedelta(seconds=30)', text)
        self.assertIn('timedelta(seconds=180)', text)
        self.assertIn('--offset-seconds 30', text)
        self.assertIn('--offset-seconds 180', text)
        self.assertNotIn('sleep 30', text)
        self.assertNotIn('sleep 180', text)

    def test_workflow_enforces_roi_first_and_nonaccrual_semantics(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('REALIZED_ROI_ON_FILLED_WAGERS', text)
        self.assertIn('DETECTOR_PROCESS_CHECK_NOT_EDGE_VALIDATION', text)
        self.assertIn('execution-pilot.json', text)
        self.assertIn('counts_as_independent_context_class == false', text)

    def test_data_push_does_not_continue_after_failed_rebase(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        self.assertIn('if ! git rebase origin/data; then', text)
        self.assertIn('continue', text)
        self.assertNotIn('git rebase origin/data || git rebase --abort || true', text)


if __name__ == '__main__':
    unittest.main()
