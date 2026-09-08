from pathlib import Path
import unittest
class LastNoteTests(unittest.TestCase):
    def test_no_suite_claim(self):self.assertIn("have not been claimed",Path("docs/BINDING_LAST_NOTE.txt").read_text())
if __name__=="__main__":unittest.main()
