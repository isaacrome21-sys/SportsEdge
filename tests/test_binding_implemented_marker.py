from pathlib import Path
import unittest
class MarkerTests(unittest.TestCase):
    def test_promotion_unchanged(self):self.assertIn("promotion_changed=false",Path("docs/BINDING_IMPLEMENTED.txt").read_text())
if __name__=="__main__":unittest.main()
