from pathlib import Path
import unittest


class ProviderUsageUnknownTests(unittest.TestCase):
    def test_writer_does_not_infer_missing_quota(self):
        text = Path("scripts/provider_usage_attribution.py").read_text()
        self.assertIn('"cost_inference": "OBSERVED_DELTA" if delta is not None else "UNKNOWN"', text)
        self.assertIn('delta = None', text)


if __name__ == "__main__":
    unittest.main()
