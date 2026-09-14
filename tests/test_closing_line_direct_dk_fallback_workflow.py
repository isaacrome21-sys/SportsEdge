import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/closing-line-archive.yml"


class ClosingLineDirectDKFallbackWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_existing_schedule_is_not_expanded(self):
        self.assertIn("cron: '1,6,11,16,21,26,31,36,41,46,51,56 * * * *'", self.text)
        self.assertEqual(self.text.count("cron:"), 1)

    def test_fallback_is_exactly_scoped_to_paid_401(self):
        condition = "steps.capture.outputs.rc != '0' && steps.capture.outputs.reason == 'CLOSING_LINE_ARCHIVE_HTTP_401'"
        self.assertGreaterEqual(self.text.count(condition), 2)
        self.assertIn("Paid archive failed outside the admitted 401 fallback boundary", self.text)

    def test_fallback_rows_remain_zero_authority_transport(self):
        self.assertIn("scripts/capture_direct_dk_closing_lines.py", self.text)
        self.assertIn("archive/direct-dk", self.text)
        self.assertIn("[NOT_EVIDENCE]", self.text)

    def test_paid_401_still_fails_workflow_after_fallback_persistence(self):
        self.assertIn("Keep paid-provider 401 fail-closed after fallback persistence", self.text)
        self.assertIn("paid/multi-book source remains blocked", self.text)
        self.assertIn("exit 2", self.text)


if __name__ == "__main__":
    unittest.main()
