from pathlib import Path
import unittest
class PromotionLockTests(unittest.TestCase):
    def test_no_promotion(self):self.assertIn("No change on this branch authorizes market promotion",Path("docs/BINDING_PROMOTION_LOCK.md").read_text())
if __name__=="__main__":unittest.main()
