"""Regression tests for the frozen NFL 2026 confirmation-capture contract.

These tests intentionally exercise only deterministic local logic. They never call
an odds provider and never create confirmation evidence in the repository.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nfl_2026_line_capture.py"
CONFIG = ROOT / "config" / "nfl_2026_capture.json"
WORKFLOW = ROOT / ".github" / "workflows" / "nfl-2026-line-capture.yml"


def load_capture_module():
    spec = importlib.util.spec_from_file_location("nfl_2026_line_capture", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def capture():
    return load_capture_module()


@pytest.fixture(scope="module")
def cfg():
    return json.loads(CONFIG.read_text())


def dt_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_frozen_config_matches_confirmation_policy(cfg):
    assert cfg["capture_config_version"] == "nfl_2026_capture_v1"
    assert cfg["opener_weekday"] == "Tuesday"
    assert cfg["opener_local_time"] == "09:00"
    assert cfg["opener_window_minutes"] == 60
    assert cfg["final_minutes_before_kickoff"] == 30
    assert cfg["final_window_minutes"] == 15
    assert cfg["timezone"] == "America/Chicago"
    assert cfg["week1_tuesday_local_date"] == "2026-09-08"
    assert cfg["first_week"] == 2
    assert cfg["bookmaker"] == "draftkings"
    assert cfg["markets"] == ["spreads", "totals"]


def test_week2_opener_starts_exactly_9am_chicago(capture, cfg):
    # September 15, 2026 is still CDT (UTC-05:00), so 09:00 CT = 14:00 UTC.
    assert capture.opener_due(dt_utc("2026-09-15T13:59:59Z"), cfg) is None

    due = capture.opener_due(dt_utc("2026-09-15T14:00:00Z"), cfg)
    assert due is not None
    assert due["week"] == 2
    assert due["target"].isoformat() == "2026-09-15T09:00:00-05:00"


def test_week2_opener_closes_at_10am_chicago(capture, cfg):
    assert capture.opener_due(dt_utc("2026-09-15T14:59:59Z"), cfg) is not None
    assert capture.opener_due(dt_utc("2026-09-15T15:00:00Z"), cfg) is None


def test_week1_tuesday_is_explicitly_ineligible(capture, cfg):
    assert capture.opener_due(dt_utc("2026-09-08T14:00:00Z"), cfg) is None


def test_opener_uses_timezone_database_after_dst_change(capture, cfg):
    # On November 10 Chicago is CST (UTC-06:00), so 09:00 CT = 15:00 UTC.
    assert capture.opener_due(dt_utc("2026-11-10T14:59:59Z"), cfg) is None
    due = capture.opener_due(dt_utc("2026-11-10T15:00:00Z"), cfg)
    assert due is not None
    assert due["target"].isoformat() == "2026-11-10T09:00:00-06:00"


def test_write_new_refuses_to_overwrite_existing_capture(capture, tmp_path):
    target = tmp_path / "opener.json"
    capture.write_new(target, {"first": True})

    with pytest.raises(capture.CaptureError, match="REFUSING_OVERWRITE"):
        capture.write_new(target, {"first": False})

    assert json.loads(target.read_text()) == {"first": True}


def test_hash_lock_detects_changed_provenance(capture, tmp_path):
    local_cfg = {"output_dir": str(tmp_path)}
    now = dt_utc("2026-09-15T14:00:00Z")
    baseline = {"policy_sha256": "a", "config_sha256": "b", "script_sha256": "c"}

    assert capture.lock_status(local_cfg, baseline, now, create=True) == "LOCK_CREATED"
    assert capture.lock_status(local_cfg, baseline, now, create=False) == "MATCH"

    changed = dict(baseline, script_sha256="different")
    assert capture.lock_status(local_cfg, changed, now, create=False) == "MISMATCH:script_sha256"


def test_workflow_keeps_polling_but_gates_paid_capture():
    text = WORKFLOW.read_text()
    assert "schedule:" in text
    assert "cron: '3,13,23,33,43,53 * * * *'" in text
    assert "Gate scheduled run to a frozen capture window using free schedule data" in text
    assert "steps.due.outputs.due == 'true'" in text
    assert "github.event_name == 'schedule' && 'capture'" in text
    assert "cancel-in-progress: false" in text


def test_manual_default_is_check_not_capture():
    text = WORKFLOW.read_text()
    assert "options: [check, capture]" in text
    assert "default: check" in text
