from pathlib import Path
import unittest


class ProviderFrozenDiffContractTests(unittest.TestCase):
    def test_ci_checks_all_three_frozen_paths(self):
        text = Path(".github/workflows/market-provider-contract.yml").read_text()
        for path in (
            "scripts/nfl_2026_line_capture.py",
            "config/nfl_2026_capture.json",
            ".github/workflows/nfl-2026-line-capture.yml",
        ):
            self.assertIn(path, text)
        self.assertIn("git diff --name-only origin/main...HEAD", text)


if __name__ == "__main__":
    unittest.main()
