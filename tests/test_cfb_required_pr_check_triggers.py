"""Required CFB PR checks must not be suppressed by path filters.

The historical totals and spread PRs changed only research files and GitHub
required checks stayed in "Expected" despite other workflows passing.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    ".github/workflows/cfb-sdv-card.yml",
    ".github/workflows/cfb-market-anchored-spread-fit.yml",
)


class RequiredCFBCheckTriggerTest(unittest.TestCase):
    def test_mandatory_checks_run_for_research_only_prs(self):
        for path in REQUIRED:
            with self.subTest(workflow=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertRegex(text, r"(?m)^  pull_request:\s*$")
                pr = re.search(r"(?ms)^  pull_request:\s*\n(.*?)(?=^  [a-z_]+:|^permissions:|\Z)", text)
                self.assertIsNotNone(pr, path)
                self.assertNotRegex(pr.group(1), r"(?m)^    paths(?:-ignore)?:")
                self.assertRegex(text, r"(?m)^  workflow_dispatch:")

    def test_no_betting_authority_change(self):
        # Regression file guards workflow metadata only; the card's
        # existing fail-closed model evidence flag remains empty.
        code = (ROOT / "scripts/run_cfb_sdv_card_v2.py").read_text()
        self.assertIn("VALIDATED_MARKETS: frozenset = frozenset()", code)


if __name__ == "__main__":
    unittest.main()
