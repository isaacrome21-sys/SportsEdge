from pathlib import Path
import unittest


class ProviderPRBodyTests(unittest.TestCase):
    def test_pr_body_has_required_scope(self):
        text = Path("docs/provider_abstraction_pr_body.md").read_text()
        for value in (
            "ESPN_SCOREBOARD",
            "provider.displayName",
            "ML/RL/totals",
            "PARTIALLY_PROVEN",
            "No changes to `scripts/nfl_2026_line_capture.py`",
            "No Model_P",
            "Do not merge until `market-provider-contract` is green",
        ):
            self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
