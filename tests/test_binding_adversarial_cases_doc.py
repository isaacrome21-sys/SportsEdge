from pathlib import Path
import unittest
class AdversarialDocTests(unittest.TestCase):
    def test_inventory_contains_threshold_and_event(self):
        t=Path("docs/BINDING_ADVERSARIAL_CASES.md").read_text();self.assertIn("probability threshold",t);self.assertIn("canonical event instance",t)
if __name__=="__main__":unittest.main()
