from pathlib import Path
import unittest
class ReadyTests(unittest.TestCase):
    def test_ci_not_promotion(self):
        t=Path("docs/BINDING_PATCH_READY.txt").read_text();self.assertIn("READY_FOR_CI",t);self.assertIn("NOT_READY_FOR_PRODUCTION_PROMOTION",t)
if __name__=="__main__":unittest.main()
