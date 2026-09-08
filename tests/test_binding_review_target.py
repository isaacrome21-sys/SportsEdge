from pathlib import Path
import unittest
class TargetTests(unittest.TestCase):
    def test_target(self):self.assertIn("no priced row bypasses",Path("docs/BINDING_REVIEW_TARGET.txt").read_text())
if __name__=="__main__":unittest.main()
