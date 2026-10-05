"""Research completion must not be treated as malformed betting lines."""
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from scripts import intake_mlb_lines_issue as intake


@pytest.mark.parametrize("returncode, expected", [(0, 3), (1, 4)])
def test_research_exit_codes(monkeypatch, tmp_path, returncode, expected):
    monkeypatch.chdir(tmp_path)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stderr="research error", stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert intake.run_research("f5_nrfi_tightening", "1") == expected
    if returncode == 0:
        assert len(calls) == 2
        assert calls[1][:3] == ["gh", "issue", "comment"]
        assert not (tmp_path / "intake_error.txt").exists()
    else:
        assert len(calls) == 1
        assert "RESEARCH_DIRECTIVE_FAILED" in (tmp_path / "intake_error.txt").read_text()


@pytest.mark.parametrize("intake_status, shell_status, comment", [
    (0, 0, None), (3, 0, None), (4, 1, "research run failed"),
    (2, 1, "Couldn't read these lines"),
])
def test_workflow_routes_status_without_rerunning_research(tmp_path, intake_status, shell_status, comment):
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/mlb-lines-issue.yml").read_text())
    steps = workflow["jobs"]["card"]["steps"]
    script = next(s["run"] for s in steps if s.get("id") == "intake")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text('#!/bin/bash\necho "path=test.json"\necho "test status" > intake_error.txt\nexit "$TEST_INTAKE_STATUS"\n')
    fake_python.chmod(0o755)
    fake_gh = bin_dir / "gh"
    fake_gh.write_text('#!/bin/bash\ncp comment.md posted.md\n')
    fake_gh.chmod(0o755)
    output = tmp_path / "output"
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
           "TEST_INTAKE_STATUS": str(intake_status), "GITHUB_OUTPUT": str(output),
           "BODY": "RESEARCH f5_nrfi_tightening", "OBSERVED": "2026-10-05T00:00:00Z", "ISSUE": "1"}
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == shell_status, result.stderr
    if comment:
        posted = (tmp_path / "posted.md").read_text()
        assert comment in posted
        if intake_status == 4:
            assert "Edit the issue" not in posted
    else:
        assert not (tmp_path / "posted.md").exists()
    if intake_status == 3:
        assert "research_complete=true" in output.read_text()
        for name in ("Run SportsEdge engines", "Render PRE-CONTEXT result and reply now", "Retrieve pregame context and post final card"):
            assert next(s for s in steps if s.get("name") == name)["if"] == "steps.intake.outputs.research_complete != 'true'"
