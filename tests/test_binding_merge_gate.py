from pathlib import Path
import unittest
class MergeGateTests(unittest.TestCase):
    def test_full_suite_required(self):self.assertIn("full repository tests",Path("docs/BINDING_MERGE_GATE.md").read_text())
if __name__=="__main__":unittest.main()
