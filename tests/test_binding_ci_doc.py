from pathlib import Path
import unittest
class CIDocTests(unittest.TestCase):
    def test_full_suite_is_merge_gate(self):self.assertIn("full suite",Path("docs/BINDING_CI_COMMAND.md").read_text())
if __name__=="__main__":unittest.main()
