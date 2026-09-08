from pathlib import Path
import unittest
class AcceptanceCriteriaTests(unittest.TestCase):
    def test_unit_spec_is_not_pass(self):self.assertIn("unit-only spec declaration is not PASS",Path("docs/BINDING_ACCEPTANCE_CRITERIA.md").read_text())
if __name__=="__main__":unittest.main()
