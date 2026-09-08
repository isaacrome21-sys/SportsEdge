from pathlib import Path
import unittest
class SourceTruthTests(unittest.TestCase):
    def test_layers_separate(self):self.assertIn("No layer may substitute",Path("docs/BINDING_SOURCE_OF_TRUTH.md").read_text())
if __name__=="__main__":unittest.main()
