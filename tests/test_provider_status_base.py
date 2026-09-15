import json
from pathlib import Path
import unittest


class ProviderStatusBaseTests(unittest.TestCase):
    def test_status_binds_expected_base(self):
        row = json.loads(Path("docs/provider_abstraction_status.json").read_text())
        self.assertEqual(row["base_sha"], "abaed7e4351f8579404dc725a4c736a0bff00ba8")
        self.assertEqual(row["branch"], "feat/free-provider-abstraction-20260915")


if __name__ == "__main__":
    unittest.main()
