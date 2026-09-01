from pathlib import Path
import unittest


WORKFLOW = Path('.github/workflows/auto-mlb.yml')


def _step(text: str, name: str) -> str:
    marker = f'- name: {name}'
    if marker not in text:
        raise AssertionError(f'missing workflow step: {name}')
    tail = text.split(marker, 1)[1]
    return tail.split('\n      - name:', 1)[0]


class AutoMlbWorkflowKeyConservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    def test_scheduled_run_keeps_15_minute_heartbeat(self):
        self.assertIn("cron: '*/15 * * * *'", self.text)

    def test_odds_diagnostic_is_dispatch_only(self):
        block = _step(self.text, 'Diagnose Odds API credentials safely')
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        self.assertIn('SPORTSEDGE_ODDS_API_KEY:', block)

    def test_featured_odds_probe_is_dispatch_only(self):
        block = _step(self.text, 'Acquire featured MLB game lines')
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        self.assertIn('SPORTSEDGE_ODDS_API_KEY:', block)

    def test_scheduled_machine_has_no_odds_or_external_quote_secrets(self):
        block = _step(self.text, 'Run scheduled MLB machine without Odds API credits')
        self.assertIn("if: github.event_name != 'workflow_dispatch'", block)
        self.assertNotIn('SPORTSEDGE_ODDS_API_KEY', block)
        self.assertNotIn('SPORTSEDGE_QUOTES_URL', block)
        self.assertIn('run_auto_mlb_resilient.py', block)

    def test_requested_run_owns_full_keyring(self):
        block = _step(self.text, 'Run requested canonical automated MLB machine')
        self.assertIn("if: github.event_name == 'workflow_dispatch'", block)
        for name in (
            'SPORTSEDGE_ODDS_API_KEY:',
            'SPORTSEDGE_ODDS_API_KEY_2:',
            'SPORTSEDGE_ODDS_API_KEY_3:',
            'SPORTSEDGE_ODDS_API_KEY_4:',
        ):
            self.assertIn(name, block)
        self.assertIn('run_auto_mlb_resilient.py', block)

    def test_only_dispatch_steps_reference_odds_api_secrets(self):
        # Guard against a later scheduled step accidentally reintroducing free-key burn.
        lines = self.text.splitlines()
        secret_refs = [i for i, line in enumerate(lines) if 'secrets.SPORTSEDGE_ODDS_API_KEY' in line]
        self.assertGreaterEqual(len(secret_refs), 8)
        for index in secret_refs:
            prior = '\n'.join(lines[max(0, index - 12):index + 1])
            self.assertTrue(
                'Diagnose Odds API credentials safely' in prior
                or 'Acquire featured MLB game lines' in prior
                or 'Run requested canonical automated MLB machine' in prior,
                prior,
            )


if __name__ == '__main__':
    unittest.main()
