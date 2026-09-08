from pathlib import Path
import unittest
class NextExecutionTests(unittest.TestCase):
    def test_ci_next(self):self.assertIn("Run CI/full tests",Path("docs/BINDING_NEXT_EXECUTION.md").read_text())
if __name__=="__main__":unittest.main()
