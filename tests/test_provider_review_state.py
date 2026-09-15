from pathlib import Path
import unittest


class ProviderReviewStateTests(unittest.TestCase):
    def test_review_checklist_has_one_open_item(self):
        rows = [x for x in Path("docs/provider_abstraction_review_checklist.md").read_text().splitlines() if x.startswith("- [")]
        self.assertEqual(sum("- [ ]" in x for x in rows), 1)
        self.assertIn("market-provider-contract", next(x for x in rows if "- [ ]" in x))


if __name__ == "__main__":
    unittest.main()
