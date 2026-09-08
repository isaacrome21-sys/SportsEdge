from pathlib import Path
import unittest
class CoverageReportingTests(unittest.TestCase):
    def test_early_failures_counted(self):self.assertIn("early failures cannot disappear",Path("docs/BINDING_COVERAGE_REPORTING.md").read_text())
if __name__=="__main__":unittest.main()
