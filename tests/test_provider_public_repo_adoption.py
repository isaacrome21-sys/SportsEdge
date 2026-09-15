from pathlib import Path
import unittest


class ProviderPublicRepoAdoptionTests(unittest.TestCase):
    def test_adoption_is_pattern_not_untracked_vendor_code(self):
        text = Path("docs/free_provider_public_repo_adoption.md").read_text()
        self.assertIn("does not vendor or copy third-party source code", text)
        self.assertIn("provider adapter separated from model logic", text)
        self.assertIn("unsupported markets fail closed", text)
        self.assertIn("free-first routing", text)


if __name__ == "__main__":
    unittest.main()
