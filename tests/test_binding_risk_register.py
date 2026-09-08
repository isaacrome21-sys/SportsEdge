from pathlib import Path
import unittest
class RiskTests(unittest.TestCase):
    def test_p0s_recorded(self):
        t=Path("docs/BINDING_RISK_REGISTER.md").read_text();self.assertIn("P0",t);self.assertIn("cross-event",t)
if __name__=="__main__":unittest.main()
