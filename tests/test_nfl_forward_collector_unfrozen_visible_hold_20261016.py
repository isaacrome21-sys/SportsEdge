"""Regression: UNFROZEN M2 must not produce misleading green NFL CLV collector runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/require_nfl_forward_release.py"
WORKFLOW = ROOT / ".github/workflows/football-nfl-forward-clv-collection.yml"


def _exercise(tmp_path, payload):
    root = tmp_path / "run"
    root.mkdir()
    status = root / "release-status.json"
    if payload is not None:
        status.write_text(json.dumps(payload), encoding="utf-8")
    summary = root / "summary.md"
    env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--status-file", str(status)],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    return result, summary.read_text(encoding="utf-8")


def test_unfrozen_model_is_a_visible_failed_collection(tmp_path):
    p, summary = _exercise(tmp_path, {"state": "CURRENT_MAIN_MODEL_NOT_FROZEN", "freeze_status": "UNFROZEN"})
    assert p.returncode != 0
    assert "NFL_FORWARD_COLLECTION_BLOCKED:CURRENT_MAIN_MODEL_NOT_FROZEN:freeze=UNFROZEN" in p.stdout
    assert "no decisions" in summary.lower()
    assert "backfilled" in summary


def test_missing_status_fails_visibly(tmp_path):
    p, summary = _exercise(tmp_path, None)
    assert p.returncode != 0
    assert "RELEASE_STATUS_MISSING_OR_INVALID" in p.stdout
    assert "BLOCKED" in summary


def test_rejected_release_artifact_fails_visibly(tmp_path):
    p, _ = _exercise(tmp_path, {"state": "LATEST_SUCCESSFUL_RELEASE_NOT_FROZEN_ARTIFACT"})
    assert p.returncode != 0
    assert "LATEST_SUCCESSFUL_RELEASE_NOT_FROZEN_ARTIFACT" in p.stdout


def test_workflow_release_gate_precedes_all_capture_steps():
    source = WORKFLOW.read_text(encoding="utf-8")
    release = source.index("- name: Resolve latest successful main production-model release")
    refusal = source.index("- name: Refuse green collection when release is unavailable")
    checkout = source.index("- name: Checkout exact model-release implementation")
    assert release < refusal < checkout
    guard = source[refusal:checkout]
    assert "if: steps.release.outputs.available != 'true'" in guard
    assert "python3 scripts/require_nfl_forward_release.py" in guard
    assert "exit 0" not in guard
    assert "steps.release.outputs.available == 'true'" in source[checkout:]
