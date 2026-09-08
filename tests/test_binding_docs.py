from pathlib import Path
import unittest
class NextTests(unittest.TestCase):
    def test_adapter_is_next_source_boundary(self):
        t=Path("docs/BINDING_NEXT.md").read_text();self.assertIn("acquisition adapters",t);self.assertIn("Do not derive these from model output",t)
if __name__=="__main__":unittest.main()
