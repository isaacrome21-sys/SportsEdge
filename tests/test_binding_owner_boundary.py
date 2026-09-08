from pathlib import Path
import unittest
class OwnerTests(unittest.TestCase):
    def test_truth_gate_owns_promotion(self):self.assertIn("Truth Gate owns promotion",Path("docs/BINDING_OWNER_BOUNDARY.md").read_text())
if __name__=="__main__":unittest.main()
