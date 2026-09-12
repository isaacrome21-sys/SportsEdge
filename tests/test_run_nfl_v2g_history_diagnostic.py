import csv
import json
import subprocess
import sys
from pathlib import Path


def _write_csv(path: Path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _schedule_row():
    return {
        "game_id": "2025_01_A_B", "season": 2025, "week": 1, "game_type": "REG",
        "home_team": "A", "away_team": "B", "home_score": 21, "away_score": 17,
        # These provider columns may exist in the source file, but the diagnostic
        # runner must not project them into V2G event rows.
        "spread_line": -3, "total_line": 44, "home_spread_odds": -110,
        "away_spread_odds": -110, "over_odds": -110, "under_odds": -110,
    }


def test_runner_fails_closed_when_td_team_missing(tmp_path):
    schedule = tmp_path / "schedule.csv"
    pbp = tmp_path / "pbp.csv"
    out = tmp_path / "events.json"
    manifest = tmp_path / "manifest.json"
    _write_csv(schedule, list(_schedule_row()), [_schedule_row()])
    fields = ["game_id", "drive", "posteam", "touchdown", "play_type", "field_goal_result"]
    _write_csv(pbp, fields, [{"game_id":"2025_01_A_B","drive":1,"posteam":"A","touchdown":1,"play_type":"pass","field_goal_result":""}])
    proc = subprocess.run([sys.executable, "scripts/run_nfl_v2g_history_diagnostic.py", "--schedule", str(schedule), "--pbp", str(pbp), "--output", str(out), "--manifest-output", str(manifest)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "NFL_V2G_REQUIRED_SOURCE_FIELDS_MISSING" in (proc.stderr + proc.stdout)
    assert not manifest.exists()


def test_runner_writes_market_blind_research_only_manifest(tmp_path):
    schedule = tmp_path / "schedule.csv"
    pbp = tmp_path / "pbp.csv"
    out = tmp_path / "events.json"
    manifest = tmp_path / "manifest.json"
    _write_csv(schedule, list(_schedule_row()), [_schedule_row()])
    fields = ["game_id", "drive", "posteam", "touchdown", "td_team", "play_type", "field_goal_result"]
    rows = [
        {"game_id":"2025_01_A_B","drive":1,"posteam":"A","touchdown":1,"td_team":"A","play_type":"pass","field_goal_result":""},
        {"game_id":"2025_01_A_B","drive":2,"posteam":"B","touchdown":0,"td_team":"","play_type":"field_goal","field_goal_result":"made"},
    ]
    _write_csv(pbp, fields, rows)
    proc = subprocess.run([sys.executable, "scripts/run_nfl_v2g_history_diagnostic.py", "--schedule", str(schedule), "--pbp", str(pbp), "--output", str(out), "--manifest-output", str(manifest)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    event_rows = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "RESEARCH_DIAGNOSTIC_ONLY"
    assert payload["historical_evidence_integrity"] == "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT"
    assert payload["market_blind_input_contract"] is True
    assert payload["promotion_authority"] is False
    assert payload["official_status_granted"] is False
    assert payload["nfl_props"] == "NO_ENGINE"
    assert payload["event_rows"] == 1
    assert len(payload["schedule"]["sha256"]) == 64
    assert len(payload["pbp"][0]["sha256"]) == 64
    assert len(payload["event_rows_sha256"]) == 64
    forbidden = set(payload["forbidden_market_fields"])
    assert forbidden
    assert forbidden.isdisjoint(event_rows[0])
