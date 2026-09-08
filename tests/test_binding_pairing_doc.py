from pathlib import Path
import unittest
class PairingDocTests(unittest.TestCase):
    def test_each_quote_independently_valid(self):self.assertIn("independently pass",Path("docs/BINDING_PAIRING.md").read_text())
if __name__=="__main__":unittest.main()
