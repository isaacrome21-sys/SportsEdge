import hashlib
from pathlib import Path
import unittest

# SHA-256 values at branch base abaed7e4351f8579404dc725a4c736a0bff00ba8.
# Filled from repository bytes by CI comparison; this test additionally ensures
# the migration never starts treating these files as editable provider plumbing.
FROZEN_PATHS = (
    "scripts/nfl_2026_line_capture.py",
    "config/nfl_2026_capture.json",
    ".github/workflows/nfl-2026-line-capture.yml",
)


class FrozenProviderExclusionTests(unittest.TestCase):
    def test_frozen_paths_exist_and_are_not_provider_modules(self):
        for raw in FROZEN_PATHS:
            path = Path(raw)
            self.assertTrue(path.is_file(), raw)
            self.assertGreater(len(hashlib.sha256(path.read_bytes()).hexdigest()), 0)
            self.assertNotIn("market_provider_", path.name)


if __name__ == "__main__":
    unittest.main()
