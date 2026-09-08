from pathlib import Path
import unittest
class ReadoutReqTests(unittest.TestCase):
    def test_no_post_compute_quote_copy(self):self.assertIn("must not be copied from a sportsbook quote",Path("docs/BINDING_READOUT_REQUIREMENTS.md").read_text())
if __name__=="__main__":unittest.main()
