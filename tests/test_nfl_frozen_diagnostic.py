import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def test_diagnostic_rejects_another_code_commit_before_loading_sources(tmp_path):
    bundle=tmp_path/'bundle'
    bundle.mkdir()
    (bundle/'nfl_production_validation.json').write_text(json.dumps({'code_git_sha':'0'*40}))
    result=subprocess.run([sys.executable,str(ROOT/'scripts/diagnose_nfl_frozen_attempt.py'),'--frozen-repo',str(ROOT),'--attempt-bundle',str(bundle),'--output',str(tmp_path/'out.json')],capture_output=True,text=True)
    assert result.returncode != 0
    assert 'BLOCKED_FROZEN_CODE_SHA_MISMATCH' in result.stderr
    assert not (tmp_path/'out.json').exists()
