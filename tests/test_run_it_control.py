import json
from pathlib import Path
import subprocess
import sys

import pytest

from sportsedge.run_it_control import (
    RunItControlError,
    audit_surface,
    execute_surface,
    scope_from_request,
)

ROOT = Path(__file__).resolve().parents[1]


def _surface(root: Path, sports: dict) -> Path:
    path = root / "config" / "run_it_surface.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": "RUN_IT_CONTROL_V1", "sports": sports}))
    return path


def test_repo_surface_declares_all_active_sports_and_live_lane():
    report = audit_surface()
    assert report["status"] == "PASS"
    assert {row["sport"] for row in report["sports"]} == {
        "MLB", "NFL", "CFB", "PGA", "UFC", "LIVE"
    }


def test_run_it_cli_executes_by_path_from_repo_root(tmp_path):
    output = tmp_path / "audit.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_it_all.py"),
            "--audit",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"


def test_execute_never_silently_skips_library_only_lane(tmp_path):
    _surface(tmp_path, {
        "CFB": {
            "lane": "PREGAME_MODEL",
            "automatic_command": None,
            "library_entrypoint": "sportsedge.sports.cfb.run_machine:run_it_cfb",
            "automatic_completeness": "LIBRARY_ONLY",
            "blocker": "CFB_AUTO_CLI_REQUIRED",
        }
    })
    report = execute_surface(repo_root=tmp_path, scope=("CFB",))
    assert report["overall_status"] == "BLOCKED"
    assert report["results"][0]["sport"] == "CFB"
    assert report["results"][0]["status"] == "BLOCKED"
    assert report["results"][0]["blocker"] == "CFB_AUTO_CLI_REQUIRED"


def test_execute_runs_declared_entrypoint_and_preserves_governance(tmp_path):
    script = tmp_path / "scripts" / "ok.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n")
    _surface(tmp_path, {
        "MLB": {
            "lane": "PREGAME_MODEL",
            "automatic_command": ["python", "scripts/ok.py"],
            "automatic_completeness": "FULL_FAIL_CLOSED",
        }
    })
    report = execute_surface(repo_root=tmp_path, scope=("MLB",))
    assert report["overall_status"] == "SUCCESS"
    assert report["results"][0]["exit_code"] == 0
    assert report["governance"] == {
        "model_p_changed": False,
        "truth_gate_changed": False,
        "promotion_changed": False,
        "silent_skip_allowed": False,
    }


def test_unknown_scope_fails_closed(tmp_path):
    _surface(tmp_path, {
        "MLB": {"lane": "PREGAME_MODEL", "automatic_command": None}
    })
    with pytest.raises(RunItControlError, match="RUN_IT_SCOPE_UNKNOWN"):
        execute_surface(repo_root=tmp_path, scope=("NBA",))


def test_request_scope_all_and_subset():
    assert scope_from_request({"scope": "ALL"}) is None
    assert scope_from_request({"scope": "MLB,NFL"}) == ("MLB", "NFL")
    assert scope_from_request({"scope": ["PGA", "UFC"]}) == ("PGA", "UFC")


@pytest.mark.parametrize("script", ["run_auto_mlb_resilient.py", "build_nfl_auto_context.py", "run_cfb_auto.py"])
def test_sport_entrypoint_needs_no_pythonpath(script):
    import os
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "scripts/" + script, "--help"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("exit_code", [0, 2])
def test_structured_block_never_becomes_success(tmp_path, exit_code):
    script = tmp_path / "scripts" / "blocked.py"
    script.parent.mkdir(parents=True)
    script.write_text('import json\nprint(json.dumps({"status":"BLOCKED","reason":"SOURCE_UNAVAILABLE"}))\nraise SystemExit(' + str(exit_code) + ')\n')
    _surface(tmp_path, {"MLB": {"automatic_command": ["python", "scripts/blocked.py"]}})
    result = execute_surface(repo_root=tmp_path)["results"][0]
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == "SOURCE_UNAVAILABLE"
