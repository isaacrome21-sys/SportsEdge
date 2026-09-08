from pathlib import Path
import unittest
class ChangelogTests(unittest.TestCase):
    def test_no_false_completion(self):self.assertIn("no false 38/38",Path("docs/BINDING_CHANGELOG.md").read_text())
if __name__=="__main__":unittest.main()
