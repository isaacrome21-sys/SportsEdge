"""End-to-end execution test for read-only research CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ask_nfl_sims.py"


def _invoke(tmp_path, question, price=None):
    paths = [
        {"home_score": 10, "away_score": 17},
        {"home_score": 10, "away_score": 16},
        {"home_score": 35, "away_score": 10},
        {"home_score": 20, "away_score": 20},
    ]
    file = tmp_path / "paths.json"
    file.write_text(json.dumps(paths), encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--paths-json", str(file),
            "--question", question, "--home", "DEN", "--away", "SEA",
            "--alias", "Seahawks=SEA"]
    if price is not None:
        args += ["--price", str(price)]
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT,
                          env={**os.environ, "PYTHONPATH": str(ROOT)}, check=False)


def test_cli_full_research_question_to_json(tmp_path):
    done = _invoke(tmp_path, "Seahawks win by 7+", 180)
    assert done.returncode == 0, done.stderr
    row = json.loads(done.stdout)
    assert row["win_count"] == 1
    assert row["sample_count"] == 4
    assert row["price_american"] == 180
    assert row["eligible_as_bet"] is False
    assert row["picks"] == []


def test_cli_refuses_unsupported_question(tmp_path):
    done = _invoke(tmp_path, "Seahawks passing touchdowns over 2.5")
    assert done.returncode == 2
    assert json.loads(done.stderr)["reason"] == "ASK_SIMS_UNSUPPORTED_QUESTION"
    assert not done.stdout
