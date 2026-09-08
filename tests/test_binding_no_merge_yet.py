from pathlib import Path
import unittest
class MergeStateTests(unittest.TestCase):
    def test_unmerged(self):self.assertIn("intentionally unmerged",Path("docs/BINDING_NO_MERGE_YET.md").read_text())
if __name__=="__main__":unittest.main()
