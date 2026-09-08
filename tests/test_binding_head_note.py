from pathlib import Path
import unittest
class HeadNoteTests(unittest.TestCase):
    def test_no_test_claim(self):self.assertIn("Do not infer test execution",Path("docs/BINDING_BRANCH_HEAD_NOTE.md").read_text())
if __name__=="__main__":unittest.main()
