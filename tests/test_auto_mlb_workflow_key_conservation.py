from pathlib import Path
import unittest


WORKFLOW = Path('.github/workflows/auto-mlb.yml')


class AutoMlbWorkflowKeyConservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    def test_scheduled_run_keeps_15_minute_heartbeat(self):
        self.assertIn("cron: '*/15 * * * *'", self.text)

    def test_odds_diagnostic_is_dispatch_only(self):
        block = self.text.split('- name: Diagnose Odds API credentials safely', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        self.assertIn('SPORTSEDGE_ODDS_API_KEY:', block)

    def test_featured_odds_probe_is_dispatch_only(self):
        block = self.text.split('- name: Acquire featured MLB game lines', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        self.assertIn('SPORTSEDGE_ODDS_API_KEY:', block)

    def test_scheduled_machine_has_no_odds_api_secrets(self):
        block = self.text.split('- name: Run scheduled MLB machine without Odds API credits', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: github.event_name != 'workflow_dispatch'", block)
        self.assertNotIn('SPORTSEDGE_ODDS_API_KEY', block)
        self.assertNotIn('SPORTSEDGE_QUOTES_URL', block)
        self.assertIn('run_auto_mlb_resilient.py', block)

    def test_requested_run_owns_full_keyring(self):
        block = self.text.split('- name: Run requested canonical automated MLB machine', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        for name in (
            'SPORTSEDGE_ODDS_API_KEY:',
            'SPORTSEDGE_ODDS_API_KEY_2:',
            'SPORTSEDGE_ODDS_API_KEY_3:',
            'SPORTSEDGE_ODDS_API_KEY_4:',
        ):
            self.assertIn(name, block)
        self.assertIn('run_auto_mlb_resilient.py', block)


if __name__ == '__main__':
    unittest.main()
