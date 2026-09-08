from pathlib import Path
import unittest
class ClaimTests(unittest.TestCase):
    def test_not_38(self):self.assertIn("Not claimed: 38/38",Path("docs/BINDING_CLAIM.md").read_text())
if __name__=="__main__":unittest.main()
