from pathlib import Path
import unittest
class StatusHonesty(unittest.TestCase):
    def test_status_does_not_claim_complete(self):
        text=Path("docs/MLB_BINDING_WIRING_STATUS.md").read_text()
        self.assertIn("does **not** claim 38/38",text)
        self.assertIn("fail-closed",text)
if __name__=="__main__":unittest.main()
