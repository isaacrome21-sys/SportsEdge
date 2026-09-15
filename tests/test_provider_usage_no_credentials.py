from pathlib import Path
import unittest


class ProviderUsageNoCredentialsTests(unittest.TestCase):
    def test_usage_writer_has_no_key_or_secret_arguments(self):
        text = Path("scripts/provider_usage_attribution.py").read_text()
        self.assertNotIn('add_argument("--api-key"', text)
        self.assertNotIn('add_argument("--secret"', text)
        self.assertIn('"contains_credentials": False', text)


if __name__ == "__main__":
    unittest.main()
