"""Regression tests for fail-closed CFB blend backtest inputs."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backtest_cfb_matchup_blend.py"


def test_missing_requested_season_fails_closed(tmp_path):
    games = tmp_path / "games.json"
    games.write_text(json.dumps([]))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--games-json", str(games),
         "--seasons", "2024,2025,2026", "--output", str(tmp_path / "report.json")],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert result.returncode != 0
    assert "INCOMPLETE_EVALUATION" in result.stdout
    assert not (tmp_path / "report.json").exists()


def test_unpriced_input_cannot_select_blend_weight(tmp_path):
    games = tmp_path / "games.json"
    games.write_text(json.dumps([{
        "season": 2026, "week": 1, "start": "2026-09-01T18:00:00Z",
        "id": "sample", "home": "Home", "away": "Away",
        "hs": 28, "as": 21, "spread": None, "total": None,
    }]))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--games-json", str(games),
         "--seasons", "2024,2026", "--output", str(tmp_path / "report.json")],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert result.returncode != 0
    assert "INCOMPLETE_EVALUATION" in result.stdout
    assert not (tmp_path / "report.json").exists()


def test_single_season_cannot_masquerade_as_out_of_sample(tmp_path):
    games = tmp_path / "games.json"
    games.write_text("[]")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--games-json", str(games),
         "--seasons", "2026", "--output", str(tmp_path / "report.json")],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert result.returncode != 0
    assert "INVALID_EVALUATION_SEASONS" in result.stdout
    assert not (tmp_path / "report.json").exists()


def test_duplicate_or_reverse_seasons_rejected(tmp_path):
    games = tmp_path / "games.json"
    games.write_text("[]")
    for seasons in ("2025,2025,2026", "2026,2024"):
        report = tmp_path / "report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--games-json", str(games),
             "--seasons", seasons, "--output", str(report)],
            capture_output=True, text=True, cwd=ROOT, check=False,
        )
        assert result.returncode != 0
        assert "INVALID_EVALUATION_SEASONS" in result.stdout
        assert not report.exists()


def test_one_paired_game_per_season_is_insufficient(tmp_path):
    games = []
    for season in (2024, 2025):
        for i in range(4):
            games.append(dict(season=season, start=f"{season}-09-{i+1:02d}T12:00:00Z",
                              id=f"{season}-{i}", home="A", away="B",
                              hs=28, **{"as": 21}, spread=0.0, total=49.0))
    fixture = tmp_path / "games.json"
    fixture.write_text(json.dumps(games))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--games-json", str(fixture),
         "--seasons", "2024,2025", "--output", str(tmp_path / "report.json")],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert result.returncode != 0
    assert "INSUFFICIENT_EVALUATION_SAMPLE" in result.stdout
    assert not (tmp_path / "report.json").exists()
