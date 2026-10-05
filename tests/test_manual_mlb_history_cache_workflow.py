import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/manual-mlb-snapshot.yml")


class ManualMlbHistoryCacheWorkflowTests(unittest.TestCase):
    def test_manual_snapshot_restores_same_day_history_cache(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830", text)
        self.assertIn("path: .cache/mlb-history", text)
        self.assertIn("TZ=America/Chicago date +%F", text)
        self.assertIn("sportsedge/mlb_history_cache.py", text)
        self.assertIn("sportsedge/mlb_all_market_features.py", text)
        self.assertIn("--history-cache-dir .cache/mlb-history", text)

    def test_cache_is_date_and_code_surface_scoped(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("steps.history-cache-key.outputs.run_date", text)
        self.assertIn("hashFiles('sportsedge/mlb_history_cache.py', 'sportsedge/mlb_all_market_features.py', 'sportsedge/mlb_generic_features.py')", text)


if __name__ == "__main__":
    unittest.main()
