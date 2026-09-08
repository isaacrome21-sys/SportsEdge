from pathlib import Path
import unittest
class SummaryTests(unittest.TestCase):
    def test_no_predictive_or_eligibility_claim(self):
        t=Path("docs/BINDING_BRANCH_SUMMARY.md").read_text();self.assertIn("does not change predictive models",t);self.assertIn("market eligibility",t)
if __name__=="__main__":unittest.main()
