from pathlib import Path
import unittest
class SeparationTests(unittest.TestCase):
    def test_binding_not_official(self):self.assertIn("must never by itself produce `OFFICIAL_BET`",Path("docs/BINDING_TRUTH_GATE.md").read_text())
if __name__=="__main__":unittest.main()
