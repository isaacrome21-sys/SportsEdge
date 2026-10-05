import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/manual-mlb-snapshot.yml")


class ManualMlbWorkflowFallbackTests(unittest.TestCase):
    def test_code_only_push_without_live_slate_falls_back_to_regression_fixture(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("use_regression_fixture()", text)
        self.assertIn("NO_CURRENT_OR_FUTURE_MLB_SNAPSHOT_ON_CODE_PUSH", text)
        self.assertIn("NO_DATED_MLB_SNAPSHOT_ON_CODE_PUSH", text)
        self.assertIn('if [[ "$EVENT_NAME" == "push" ]]', text)
        self.assertIn('echo "live=false" >> "$GITHUB_OUTPUT"', text)

    def test_manual_dispatch_without_usable_slate_still_fails_closed(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('echo "NO_CURRENT_OR_FUTURE_MLB_SNAPSHOT" >&2', text)
        self.assertIn('echo "DATED_INPUT_NOT_LOADED: no dated manual_inputs/mlb snapshot" >&2', text)


if __name__ == "__main__":
    unittest.main()
