from pathlib import Path
import unittest
class HandoffTests(unittest.TestCase):
    def test_no_quote_copy_into_model(self):self.assertIn("must be rejected",Path("docs/BINDING_HANDOFF.md").read_text())
if __name__=="__main__":unittest.main()
