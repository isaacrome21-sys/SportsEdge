import json
from pathlib import Path
import subprocess
import sys

import pytest

from sportsedge.run_it_control import (
    RunItControlError,
    _card_state,
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
    script.write_text("import json, sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text(json.dumps({'results': [{'bet_status': 'PASS', 'model_p': 0.4}]}))\n")
    _surface(tmp_path, {
        "MLB": {
            "lane": "PREGAME_MODEL",
            "automatic_command": ["python", "scripts/ok.py", "--output", "card.json"],
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


@pytest.mark.parametrize("rows,expected", [
    ([{"bet_status": "BLOCKED", "model_p": 0.6}], "ALL_MARKETS_BLOCKED"),
    ([], "RUN_RESULTS_EMPTY"),
    ([{"bet_status": "PASS", "model_p": None}], "RUN_MODEL_PROBABILITIES_MISSING"),
])
def test_exit_zero_does_not_imply_model_ready(tmp_path, rows, expected):
    script = tmp_path / "scripts" / "card.py"
    script.parent.mkdir()
    script.write_text("from pathlib import Path\nPath('card.json').write_text(" + repr(json.dumps({"results": rows})) + ")\n")
    _surface(tmp_path, {"NFL": {"automatic_command": ["python", "scripts/card.py", "--output", "card.json"]}})
    result = execute_surface(repo_root=tmp_path)["results"][0]
    assert result["execution_status"] == "COMPLETED"
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == expected


def test_existing_card_cannot_masquerade_as_current_output(tmp_path):
    script = tmp_path / "scripts" / "noop.py"
    script.parent.mkdir()
    script.write_text("pass\n")
    (tmp_path / "card.json").write_text(json.dumps({"results": [{"bet_status": "PASS", "model_p": .5}]}))
    _surface(tmp_path, {"MLB": {"automatic_command": ["python", "scripts/noop.py", "--output", "card.json"]}})
    result = execute_surface(repo_root=tmp_path)["results"][0]
    assert result["blocker"] == "RUN_OUTPUT_NOT_REFRESHED"


@pytest.mark.parametrize("payload,status,blocker", [
    ({"status": "SUCCESS", "report": {"run_status": "BLOCKED", "results": [{"bet_status": "BLOCKED", "model_p": .6}]}}, "BLOCKED", "ALL_MARKETS_BLOCKED"),
    ({"results": [{"bet_status": "PASS", "model_p": .4}, {"bet_status": "PASS", "model_p": None}]}, "BLOCKED", "RUN_MODEL_PROBABILITIES_MISSING"),
    ({"results": [{"bet_status": "PASS", "model_p": .4}, {"bet_status": "BLOCKED", "model_p": None}]}, "PARTIAL", "SOME_MARKETS_BLOCKED_OR_DEGRADED"),
])
def test_card_health_uses_nested_report_and_each_decision(tmp_path, payload, status, blocker):
    path = tmp_path / "card.json"
    path.write_text(json.dumps(payload))
    actual = _card_state(path, None)
    assert actual[:2] == (status, blocker)
