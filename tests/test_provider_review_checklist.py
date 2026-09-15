from pathlib import Path
import unittest


class ProviderReviewChecklistTests(unittest.TestCase):
    def test_only_hosted_ci_is_unchecked(self):
        lines = Path("docs/provider_abstraction_review_checklist.md").read_text().splitlines()
        unchecked = [x for x in lines if "- [ ]" in x]
        self.assertEqual(len(unchecked), 1)
        self.assertIn("hosted CI green on exact head", unchecked[0])


if __name__ == "__main__":
    unittest.main()
