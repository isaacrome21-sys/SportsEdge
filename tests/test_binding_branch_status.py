from pathlib import Path
import unittest
class BranchStatusTests(unittest.TestCase):
    def test_status(self):
        t=Path("docs/BINDING_BRANCH_STATUS.txt").read_text();self.assertIn("EVIDENCE_PENDING",t);self.assertIn("ELIGIBILITY_UNCHANGED",t)
if __name__=="__main__":unittest.main()
