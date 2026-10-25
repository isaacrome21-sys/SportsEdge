"""CLI-level regression: strict historical provenance rejects hindsight odds."""
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_cross_sport_market_backtest.py"


def _row():
    return {
        "sport": "MLB", "market": "ML", "event_id": "fixture-1", "season": 2025,
        "event_start_ts": "2025-06-01T19:00:00Z",
        "decision_ts": "2025-06-01T18:00:00Z",
        "feature_asof_ts": "2025-06-01T17:00:00Z",
        "model_p": 0.54, "outcome": 1, "selected": True,
        "offered_decimal": 1.95, "bookmaker": "DK",
        "odds_captured_at": "2025-06-01T17:55:00Z",
    }


def _run(tmp_path, row):
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--strict-provenance",
         "--output", str(tmp_path / "report.json"), "--bootstrap-reps", "10"],
        cwd=SCRIPT.parents[1], capture_output=True, text=True, check=False,
    )


def test_strict_cli_rejects_postdecision_quote(tmp_path):
    row = _row()
    row["odds_captured_at"] = "2025-06-01T18:01:00Z"
    result = _run(tmp_path, row)
    assert result.returncode != 0
    assert "ODDS_AFTER_DECISION" in result.stderr
    assert not (tmp_path / "report.json").exists()


def test_strict_cli_accepts_valid_historical_row(tmp_path):
    result = _run(tmp_path, _row())
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["row_count"] == 1
    assert report["markets"][0]["sport"] == "MLB"
