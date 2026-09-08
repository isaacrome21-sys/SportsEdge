from pathlib import Path
import unittest
class NoSynthesisTests(unittest.TestCase):
    def test_no_backfill(self):self.assertIn("must not fill",Path("docs/BINDING_NO_SYNTHESIS.md").read_text())
if __name__=="__main__":unittest.main()
