from pathlib import Path
import unittest
class WiringDocTests(unittest.TestCase):
    def test_not_card_assembly(self):self.assertIn("Do not defer",Path("docs/BINDING_PRODUCTION_WIRING.md").read_text())
if __name__=="__main__":unittest.main()
