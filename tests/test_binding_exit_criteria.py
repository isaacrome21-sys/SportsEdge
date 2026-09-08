from pathlib import Path
import unittest
class ExitTests(unittest.TestCase):
    def test_fixture_not_enough(self):self.assertIn("No synthetic fixture alone",Path("docs/BINDING_EXIT_CRITERIA.md").read_text())
if __name__=="__main__":unittest.main()
