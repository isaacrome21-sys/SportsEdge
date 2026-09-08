from pathlib import Path
import unittest
class ExpectationTests(unittest.TestCase):
    def test_validator_not_optional(self):self.assertIn("not to make the validator optional",Path("docs/BINDING_TEST_EXPECTATION.md").read_text())
if __name__=="__main__":unittest.main()
