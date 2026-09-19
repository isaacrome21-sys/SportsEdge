from pathlib import Path
import re
import subprocess
import textwrap
import unittest


def step(name):
    text = Path('.github/workflows/nfl-2026-line-capture.yml').read_text()
    chunks = re.split(r'^      - name: ', text, flags=re.MULTILINE)
    return next(block for block in chunks[1:] if block.splitlines()[0] == name)


def shell(block):
    return textwrap.dedent(block.split('        run: |\n', 1)[1]).strip()


class NFLConfirmationPersistenceWorkflowTests(unittest.TestCase):
    def test_restore_precedes_capture_and_refuses_overwrites(self):
        text = Path('.github/workflows/nfl-2026-line-capture.yml').read_text()
        name = 'Restore immutable confirmation archive from data branch'
        restore = step(name)
        self.assertLess(text.index(name), text.index('- name: Run capture'))
        self.assertIn('_copy_create_only', restore)
        self.assertIn('origin/data', restore)
        self.assertIn("if: github.event_name != 'pull_request'", restore)
        self.assertIn("relative.name != 'attempts.jsonl'", restore)
        subprocess.run(['bash', '-n'], input=shell(restore), text=True, check=True)

    def test_capture_persistence_targets_data_not_protected_main(self):
        block = step('Commit captures and absence markers')
        self.assertIn('persist_nfl_confirmation_archive.py', block)
        self.assertNotIn('git push', block)
        self.assertNotIn('git commit', block)
        self.assertIn('set -euo pipefail', block)
        subprocess.run(['bash', '-n'], input=shell(block), text=True, check=True)

    def test_failed_persistence_keeps_run_specific_artifact(self):
        backup = step('Preserve confirmation archive even when persistence fails')
        self.assertIn('if: always()', backup)
        self.assertIn('actions/upload-artifact@', backup)
        self.assertIn('${{ github.run_id }}', backup)
        self.assertIn('${{ github.run_attempt }}', backup)
        self.assertIn('path: data/nfl_2026_confirmation/captures', backup)
