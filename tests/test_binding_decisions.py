from pathlib import Path
import unittest
class DecisionTests(unittest.TestCase):
    def test_core_decisions(self):
        t=Path("docs/BINDING_IMPLEMENTATION_DECISIONS.md").read_text();self.assertIn("explicit and required",t);self.assertIn("per-row `BLOCKED`",t)
if __name__=="__main__":unittest.main()
