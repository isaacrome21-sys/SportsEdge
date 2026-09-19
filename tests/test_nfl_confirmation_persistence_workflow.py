from pathlib import Path
import subprocess
import yaml


def steps():
    workflow = yaml.safe_load(Path('.github/workflows/nfl-2026-line-capture.yml').read_text())
    return workflow['jobs']['capture']['steps']


def test_restore_precedes_capture_and_refuses_overwrites():
    rows = steps()
    names = [row.get('name') for row in rows]
    restore = next(row for row in rows if row.get('name', '').startswith('Restore immutable'))
    assert names.index(restore['name']) < names.index('Run capture')
    assert '_copy_create_only' in restore['run']
    assert 'origin/data' in restore['run']
    assert "github.event_name != 'pull_request'" == restore['if']
    subprocess.run(['bash', '-n'], input=restore['run'], text=True, check=True)


def test_capture_persistence_targets_data_not_protected_main():
    persist = next(row for row in steps() if row.get('name') == 'Commit captures and absence markers')
    assert 'persist_nfl_confirmation_archive.py' in persist['run']
    assert 'git push' not in persist['run']
    assert 'git commit' not in persist['run']
    assert 'set -euo pipefail' in persist['run']
    subprocess.run(['bash', '-n'], input=persist['run'], text=True, check=True)


def test_failed_persistence_keeps_run_specific_artifact():
    backup = next(row for row in steps() if row.get('name', '').startswith('Preserve confirmation archive'))
    assert backup['if'].startswith('always()')
    assert backup['uses'].startswith('actions/upload-artifact@')
    assert '${{ github.run_id }}' in backup['with']['name']
    assert '${{ github.run_attempt }}' in backup['with']['name']
    assert backup['with']['path'] == 'data/nfl_2026_confirmation/captures'

