import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ProviderUsageAttributionTests(unittest.TestCase):
    def test_observed_delta_is_recorded_without_secret(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "usage.jsonl"
            subprocess.run([
                sys.executable, "scripts/provider_usage_attribution.py",
                "--out", str(out), "--lane", "TEST", "--provider", "THE_ODDS_API",
                "--endpoint", "/odds", "--markets", "TOTALS,MONEYLINE",
                "--run-id", "123", "--quota-before", "100", "--quota-after", "97",
            ], check=True, capture_output=True, text=True)
            row = json.loads(out.read_text().strip())
            self.assertEqual(row["observed_quota_delta"], 3)
            self.assertEqual(row["cost_inference"], "OBSERVED_DELTA")
            self.assertFalse(row["contains_credentials"])
            self.assertEqual(row["markets"], ["MONEYLINE", "TOTALS"])

    def test_missing_quota_is_unknown_not_inferred(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "usage.jsonl"
            subprocess.run([
                sys.executable, "scripts/provider_usage_attribution.py",
                "--out", str(out), "--lane", "TEST", "--provider", "THE_ODDS_API",
                "--endpoint", "/odds",
            ], check=True, capture_output=True, text=True)
            row = json.loads(out.read_text().strip())
            self.assertIsNone(row["observed_quota_delta"])
            self.assertEqual(row["cost_inference"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
