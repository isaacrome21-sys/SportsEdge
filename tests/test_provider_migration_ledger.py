from pathlib import Path
import unittest


class ProviderMigrationLedgerTests(unittest.TestCase):
    def test_required_consumers_and_provenance_are_visible(self):
        text = Path("docs/market_provider_migration_20260915.md").read_text()
        for required in (
            "MLB automatic / RUN IT full-game prices",
            "MLB automatic props / NRFI-YRFI / team totals / additional derivatives",
            "NFL 2026 frozen confirmation",
            "ESPN_SCOREBOARD",
            "THE_ODDS_API",
            "Exact book proof",
            "Evidence/confirmation authority",
            "Non-silent-satisfaction invariant",
        ):
            self.assertIn(required, text)

    def test_frozen_confirmation_is_explicitly_no_migration(self):
        text = Path("docs/market_provider_migration_20260915.md").read_text()
        self.assertIn("NO MIGRATION IN THIS CHANGE", text)
        self.assertIn("scripts/nfl_2026_line_capture.py", text)
        self.assertIn(".github/workflows/nfl-2026-line-capture.yml", text)


if __name__ == "__main__":
    unittest.main()
