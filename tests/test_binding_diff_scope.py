from pathlib import Path
import unittest
class ScopeTests(unittest.TestCase):
    def test_core_files_listed(self):
        t=Path("docs/BINDING_DIFF_SCOPE.md").read_text()
        for name in ("mlb_market_binding.py","quote_bridge.py","orchestrator.py","devig.py"):self.assertIn(name,t)
if __name__=="__main__":unittest.main()
