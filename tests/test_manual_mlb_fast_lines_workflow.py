import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/manual-mlb-fast-lines.yml")


class ManualMlbFastLinesWorkflowTests(unittest.TestCase):
    def test_fast_runtime_is_scoped_to_run_branch_and_manual_inputs(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("'run/mlb-fast-*'", text)
        self.assertIn("'manual_inputs/mlb/**'", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("cancel-in-progress: true", text)

    def test_fast_runtime_keeps_live_fail_closed_guards(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("FAST_MLB_REQUIRES_EXACTLY_ONE_CHANGED_INPUT", text)
        self.assertIn("FAST_MLB_PAST_SLATE_REFUSED", text)
        self.assertIn("--max-age-minutes 60", text)
        self.assertIn("tests.test_manual_mlb_live_guards", text)
        self.assertIn("tests.test_mlb_all_market_state_wiring", text)

    def test_fast_runtime_reuses_same_day_history_cache(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830", text)
        self.assertIn("path: .cache/mlb-history", text)
        self.assertIn("--history-cache-dir .cache/mlb-history", text)
        self.assertIn("mlb-history-", text)

    def test_fast_runtime_prices_same_engine_then_marks_pre_context(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/run_manual_mlb_snapshot.py", text)
        self.assertIn("scripts/render_mlb_myspari_card.py", text)
        self.assertIn("--pre-context", text)
        self.assertIn("FAST_MLB_CARD_BEGIN", text)
        self.assertIn("manual-mlb-fast-", text)


if __name__ == "__main__":
    unittest.main()
