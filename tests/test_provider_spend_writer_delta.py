import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ProviderSpendWriterDeltaTests(unittest.TestCase):
    def test_negative_consumption_delta_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.run([
                sys.executable, "scripts/provider_usage_attribution.py",
                "--out", str(Path(td) / "x.jsonl"), "--lane", "X", "--provider", "THE_ODDS_API",
                "--endpoint", "/odds", "--quota-before", "10", "--quota-after", "11",
            ], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("QUOTA_DELTA_INVALID", p.stderr + p.stdout)


if __name__ == "__main__":
    unittest.main()
