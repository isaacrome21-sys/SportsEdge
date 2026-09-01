import json
from pathlib import Path

import pytest

from sportsedge.run_it_control import (
    RunItControlError,
    audit_surface,
    execute_surface,
    scope_from_request,
)


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
