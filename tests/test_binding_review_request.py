from pathlib import Path
import unittest
class ReviewRequestTests(unittest.TestCase):
    def test_real_traversal_required(self):self.assertIn("real quote + real readout traversal",Path("docs/BINDING_REVIEW_REQUEST.md").read_text())
if __name__=="__main__":unittest.main()
