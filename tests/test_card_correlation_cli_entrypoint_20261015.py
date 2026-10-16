"""Ensure canonical RUN IT CLI executes the correlation accounting wrapper.

Regression: an earlier candidate installed the wrapper *after* the __main__
block; direct CLI execution attempted to call an undefined run_full.
Research only; no independent market evidence or betting promotion.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_emits_correlated_accounting_on_empty_no_fetch_card(tmp_path):
    lines = tmp_path / "input.json"
    out = tmp_path / "output.json"
    lines.write_text(json.dumps({"sport": "MLB", "lines": []}), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "artifacts.run_it_full",
         "--lines", str(lines), "--no-fetch", "--output", str(out)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["position_accounting"]["positions"] == 0
    assert card["position_accounting"]["accounting"] == "CORRELATED_STACK_AS_SINGLE_POSITION"
    assert card["summary"]["surfaced_positions"] == 0
