from pathlib import Path
import unittest


class ProviderChangeSummaryTests(unittest.TestCase):
    def test_summary_names_core_invariants(self):
        text = Path("docs/provider_abstraction_change_summary.md").read_text()
        for value in (
            "ESPN is transport",
            "provider.displayName",
            "60 seconds",
            "free-first",
            "PARTIALLY_PROVEN",
            "Frozen NFL 2026 confirmation",
            "No predictive or betting authority",
        ):
            self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
