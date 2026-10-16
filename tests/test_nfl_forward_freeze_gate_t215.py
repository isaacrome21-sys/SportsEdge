"""t215u Option A: cheap freeze gate ahead of the paid NFL forward collector."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/nfl_forward_freeze_gate.py"
WF = ROOT / ".github/workflows/football-nfl-forward-clv-collection.yml"
LIVENESS = ROOT / ".github/workflows/active-evidence-window-liveness.yml"
HASH = "a" * 64


def _wf(path=WF):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))
    return data


def _run(tmp_path, *args, env_extra=None):
    out = tmp_path / "out.txt"
    summ = tmp_path / "summary.md"
    env = dict(os.environ, GITHUB_OUTPUT=str(out), GITHUB_STEP_SUMMARY=str(summ), **(env_extra or {}))
    p = subprocess.run([sys.executable, str(GATE), *args], cwd=tmp_path, env=env,
                       capture_output=True, text=True, check=False)
    outputs = dict(l.split("=", 1) for l in out.read_text().splitlines() if "=" in l) if out.exists() else {}
    return p, outputs, summ.read_text() if summ.exists() else ""


def _freeze(tmp_path, payload):
    f = tmp_path / "freeze.json"
    if payload is not None:
        f.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return f


UNFROZEN = {"schema_version": 1, "status": "UNFROZEN", "hash_algorithm": "CANONICAL_JSON_SHA256_V1",
            "artifact_path": "artifacts/football/nfl_m2_model.json", "artifact_sha256": None}
FROZEN = {**UNFROZEN, "status": "FROZEN", "artifact_sha256": HASH}


def test_real_repo_freeze_is_valid_unfrozen(tmp_path):
    p, o, _ = _run(tmp_path, "check", "--freeze", str(ROOT / "config/nfl_m2_freeze.json"))
    assert p.returncode == 0 and o["frozen"] == "false"


def test_unfrozen_check_is_quiet_success(tmp_path):
    p, o, s = _run(tmp_path, "check", "--freeze", str(_freeze(tmp_path, UNFROZEN)),
                   "--now", "2026-10-16T05:30:00Z")
    assert p.returncode == 0
    assert o["frozen"] == "false"
    assert o["ct_date"] == "2026-10-16"  # 00:30 CT
    assert o["marker_key"] == "nfl-forward-m2-unfrozen-daily-2026-10-16"
    assert "::error" not in p.stdout


def test_ct_date_rolls_at_chicago_midnight(tmp_path):
    _, o, _ = _run(tmp_path, "check", "--freeze", str(_freeze(tmp_path, UNFROZEN)),
                   "--now", "2026-10-17T04:59:00Z")
    assert o["ct_date"] == "2026-10-16"
    _, o, _ = _run(tmp_path, "check", "--freeze", str(_freeze(tmp_path, UNFROZEN)),
                   "--now", "2026-10-17T05:00:00Z")
    assert o["ct_date"] == "2026-10-17"


def test_frozen_proceeds_immediately(tmp_path):
    p, o, _ = _run(tmp_path, "check", "--freeze", str(_freeze(tmp_path, FROZEN)))
    assert p.returncode == 0 and o["frozen"] == "true"


@pytest.mark.parametrize("payload,code", [
    (None, "FREEZE_FILE_MISSING"),
    ("{not json", "FREEZE_FILE_INVALID"),
    ("[]", "FREEZE_FILE_INVALID"),
    ({**UNFROZEN, "status": "frozen"}, "FREEZE_FILE_INVALID"),
    ({**UNFROZEN, "status": None}, "FREEZE_FILE_INVALID"),
    ({**UNFROZEN, "schema_version": 2}, "FREEZE_FILE_INVALID"),
    ({**FROZEN, "artifact_sha256": None}, "FREEZE_FILE_INVALID"),
    ({**FROZEN, "artifact_sha256": "A" * 64}, "FREEZE_FILE_INVALID"),
    ({**FROZEN, "artifact_sha256": "a" * 63}, "FREEZE_FILE_INVALID"),
    ({**UNFROZEN, "artifact_sha256": HASH}, "FREEZE_FILE_INVALID"),
    ({**FROZEN, "hash_algorithm": "MD5"}, "FREEZE_FILE_INVALID"),
])
def test_missing_or_invalid_freeze_fails_visibly(tmp_path, payload, code):
    p, o, s = _run(tmp_path, "check", "--freeze", str(_freeze(tmp_path, payload)))
    assert p.returncode != 0
    assert f"NFL_FORWARD_COLLECTION_BLOCKED:{code}" in p.stdout
    assert "::error" in p.stdout and "BLOCKED" in s
    assert o.get("frozen") != "true"


@pytest.mark.parametrize("event,hit,report", [
    ("schedule", "", "true"),        # first blocked scheduled run of the CT day
    ("schedule", "false", "true"),
    ("schedule", "true", "false"),   # marker exists: quiet skip
    ("workflow_dispatch", "true", "true"),
    ("workflow_dispatch", "", "true"),
])
def test_daily_rule(tmp_path, event, hit, report):
    p, o, _ = _run(tmp_path, "daily", "--event", event, "--marker-hit", hit)
    assert p.returncode == 0 and o["report"] == report


# ---- workflow structure ------------------------------------------------
def _steps(job):
    return job["steps"]


def _idx(steps, pred):
    for i, s in enumerate(steps):
        if pred(s):
            return i
    raise AssertionError("step not found")


def test_cron_still_armed_every_ten_minutes():
    wf = _wf()
    assert wf["on"]["schedule"] == [{"cron": "7,17,27,37,47,57 * * * *"}]


def test_concurrency_group_only_on_collect_not_gate_or_workflow():
    wf = _wf()
    assert "concurrency" not in wf
    jobs = wf["jobs"]
    assert "concurrency" not in jobs["freeze-gate"]
    assert jobs["collect"]["concurrency"]["group"] == "sportsedge-paid-odds-api"
    assert jobs["collect"]["needs"] == "freeze-gate"
    assert jobs["collect"]["if"].replace(" ", "") == "needs.freeze-gate.outputs.frozen=='true'"


def test_gate_job_is_cheap_and_secret_free():
    gate = _wf()["jobs"]["freeze-gate"]
    text = json.dumps(gate)
    for banned in ("secrets.", "ODDS_API", "odds_api_quota_guard", "nflverse", "curl",
                   "upload-artifact", "setup-python", "pip install", "games.csv"):
        assert banned not in text, banned
    assert gate.get("timeout-minutes", 99) <= 5
    assert gate["permissions"] == {"contents": "read"}
    assert gate["outputs"]["frozen"] == "${{ steps.freeze.outputs.frozen }}"


def test_gate_step_order_marker_before_visible_failure():
    steps = _steps(_wf()["jobs"]["freeze-gate"])
    check = _idx(steps, lambda s: s.get("id") == "freeze")
    restore = _idx(steps, lambda s: str(s.get("uses", "")).startswith("actions/cache/restore"))
    daily = _idx(steps, lambda s: s.get("id") == "daily")
    save = _idx(steps, lambda s: str(s.get("uses", "")).startswith("actions/cache/save"))
    report = _idx(steps, lambda s: "require_nfl_forward_release.py" in str(s.get("run", "")))
    assert check < restore < daily < save < report
    assert steps[restore]["with"]["lookup-only"] is True
    assert steps[restore]["with"]["key"] == steps[save]["with"]["key"] == "${{ steps.freeze.outputs.marker_key }}"
    assert "steps.freeze.outputs.frozen != 'true'" in steps[restore]["if"]
    assert "steps.daily.outputs.report == 'true'" in steps[report]["if"]
    assert "M2_UNFROZEN" in steps[report]["run"]
    assert "github.event_name == 'schedule'" in steps[save]["if"]


def test_provider_and_quota_steps_only_in_gated_collect_job():
    jobs = _wf()["jobs"]
    collect = _steps(jobs["collect"])
    for i, s in enumerate(collect):
        blob = json.dumps(s)
        if any(k in blob for k in ("odds_api_quota_guard", "fetch_nfl_forward_odds", "nflverse",
                                   "upload-artifact", "test_nfl_2026_provider_budget")):
            assert jobs["collect"]["if"]  # job never starts unless gate verified FROZEN
    assert set(jobs) == {"freeze-gate", "collect"}


def test_2365_blocked_reporting_kept_in_collect():
    src = WF.read_text()
    assert "- name: Refuse green collection when release is unavailable" in src
    assert "python3 scripts/require_nfl_forward_release.py" in src


def test_liveness_deadman_skips_while_collector_unfrozen():
    wf = _wf(LIVENESS)
    gate = wf["jobs"]["nfl-freeze-gate"]
    assert "nfl_forward_freeze_gate.py" in json.dumps(gate)
    assert "secrets." not in json.dumps(gate)
    dead = wf["jobs"]["nfl-durable-deadman"]
    assert dead["needs"] == "nfl-freeze-gate"
    cond = dead["if"]
    assert "needs.nfl-freeze-gate.outputs.frozen == 'true'" in cond
    assert "workflow_dispatch" in cond
