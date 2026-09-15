from pathlib import Path
import unittest


class ProviderMigrationTableFieldsTests(unittest.TestCase):
    def test_table_has_requested_audit_columns(self):
        text = Path("docs/market_provider_migration_20260915.md").read_text()
        header = next(x for x in text.splitlines() if x.startswith("| Consumer / lane"))
        for field in ("Previous/primary source", "Free source / routing", "Provenance label", "Markets", "Exact book proof", "Evidence/confirmation authority"):
            self.assertIn(field, header)


if __name__ == "__main__":
    unittest.main()
