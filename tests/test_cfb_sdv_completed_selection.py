import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sportsedge.sports.cfb.sdv_selection_record import RECORD, verify_completed_selection


def test_archived_result_binds_selected_serving_fit():
    record = verify_completed_selection()
    assert record["workflow_run_id"] == 37093707442
    assert record["canonical_cfbd_freeze_activated"] is False


def test_tampered_fit_rejected(tmp_path):
    record = json.loads(Path(RECORD).read_text())
    for name in (RECORD, record["result_path"], record["selected_fit_path"]):
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, dest)
    fit = tmp_path / record["selected_fit_path"]
    fit.write_text(fit.read_text() + " ")
    with pytest.raises(ValueError, match="HASH_MISMATCH:selected_fit"):
        verify_completed_selection(tmp_path)


def test_spent_attempt_refused_before_reading_training_rows(tmp_path):
    out = tmp_path / "result.json"
    run = subprocess.run([
        sys.executable, "scripts/run_cfb_sportsdataverse_bakeoff.py",
        "--rows", str(tmp_path / "nonexistent.json"),
        "--confirm", "CONSUME_ALL_FOUR_CFB_SDV_ATTEMPTS", "--out", str(out),
    ], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "."})
    assert run.returncode != 0
    assert "CFB_SDV_ATTEMPT_BUDGET_NOT_FRESH" in run.stderr
    assert not out.exists()
