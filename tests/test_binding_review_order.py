from pathlib import Path
import unittest
class OrderTests(unittest.TestCase):
    def test_do_not_weaken(self):self.assertIn("do not weaken mandatory identity",Path("docs/BINDING_REVIEW_ORDER.md").read_text())
if __name__=="__main__":unittest.main()
