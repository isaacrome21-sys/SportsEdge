import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/manual-mlb-snapshot.yml")


class ManualMlbHistoryCacheWorkflowTests(unittest.TestCase):
    def test_manual_snapshot_restores_same_day_history_cache(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830", text)
        self.assertIn("path: .cache/mlb-history", text)
        self.assertIn("TZ=America/Chicago date +%F", text)
        self.assertIn("--history-cache-dir .cache/mlb-history", text)

    def test_cache_restore_is_date_and_exact_code_surface_scoped(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        expected = "hashFiles('sportsedge/mlb_history_cache.py', 'sportsedge/mlb_all_market_features.py', 'sportsedge/mlb_generic_features.py', 'sportsedge/mlb_f5_features.py', 'sportsedge/mlb_starter_effect.py', 'sportsedge/pitcher_record_win_engine.py')"
        self.assertGreaterEqual(text.count(expected), 2)
        restore = text.split("restore-keys: |", 1)[1].split("- name: Install runtime dependencies", 1)[0]
        nonempty = [line.strip() for line in restore.splitlines() if line.strip()]
        self.assertEqual(len(nonempty), 1)
        self.assertIn(expected, nonempty[0])

    def test_priced_card_is_uploaded_before_optional_context(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        priced = text.index("- name: Upload fast priced card")
        context = text.index("- name: Retrieve pregame context")
        self.assertLess(priced, context)
        self.assertIn("name: manual-mlb-fast-priced-card", text)
        self.assertIn("compression-level: 0", text)

    def test_optional_context_uses_bounded_parallel_workers(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/acquire_mlb_card_context.py", text)
        self.assertIn("--workers 4", text)

    def test_code_push_fallback_is_preserved(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("use_regression_fixture()", text)
        self.assertIn("NO_CURRENT_OR_FUTURE_MLB_SNAPSHOT_ON_CODE_PUSH", text)


if __name__ == "__main__":
    unittest.main()
