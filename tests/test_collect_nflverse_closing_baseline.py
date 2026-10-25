"""Tests for scripts/collect_nflverse_closing_baseline.py (stdlib fixtures)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "collect_nflverse_closing_baseline.py"
)
spec = importlib.util.spec_from_file_location("collect_nflverse_closing_baseline", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

HEADER = (
    "game_id,season,week,gameday,away_team,home_team,away_score,home_score,"
    "spread_line,total_line,away_moneyline,home_moneyline\n"
)
ROWS = (
    "2024_01_BAL_KC,2024,1,2024-09-05,BAL,KC,20,27,3,48.5,150,-175\n"
    "2024_01_GB_PHI,2024,1,2024-09-06,GB,PHI,29,34,2.5,48.5,110,-130\n"
    "2019_01_GB_CHI,2019,1,2019-09-05,GB,CHI,10,3,3,46,130,-150\n"
    "2019_01_PIT_NE,2019,1,2019-09-08,PIT,NE,3,33,,50.5,,\n"
)


def test_archive_writes_csv_and_manifest(tmp_path: Path) -> None:
    manifest = mod.archive((HEADER + ROWS).encode(), tmp_path)
    assert manifest["rows"] == 4
    assert manifest["coverage"]["2024"] == {"games": 2, "closing_populated": 2}
    assert manifest["coverage"]["2019"] == {"games": 2, "closing_populated": 1}
    assert manifest["labels"]["pricing_input"] is False
    out_csv = (tmp_path / "games_closing_baseline.csv").read_text()
    assert "2024_01_BAL_KC" in out_csv
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved["archive_sha256"] == manifest["archive_sha256"]


def test_missing_column_fails_closed(tmp_path: Path) -> None:
    bad = b"game_id,season\n2024_01_BAL_KC,2024\n"
    with pytest.raises(ValueError, match="missing required columns"):
        mod.archive(bad, tmp_path)


def test_unpopulated_modern_season_fails_closed(tmp_path: Path) -> None:
    rows = "2024_01_BAL_KC,2024,1,2024-09-05,BAL,KC,,,,,,\n"
    with pytest.raises(ValueError, match="zero populated closing lines"):
        mod.archive((HEADER + rows).encode(), tmp_path)


def test_coverage_counts_only_populated() -> None:
    rows = mod.parse_games((HEADER + ROWS).encode())
    cov = mod.coverage(rows)
    assert cov[2019]["closing_populated"] == 1  # PIT_NE row lacks a spread
    assert cov[2024]["closing_populated"] == 2


def test_provenance_never_claims_dk_or_clv(tmp_path: Path) -> None:
    manifest = mod.archive((HEADER + ROWS).encode(), tmp_path)
    labels = manifest["labels"]
    assert labels["source"] == "nflverse"
    assert labels["sportsbook"] == "UNIDENTIFIED"
    assert labels["is_draftkings_quote"] is False
    assert labels["source_quote_timestamp_available"] is False
    assert labels["clv_eligible"] is False
    assert labels["pricing_input"] is False
    assert manifest["source_url"].endswith("/nflverse/nfldata/master/data/games.csv")
    assert len(manifest["source_sha256"]) == 64


def test_missing_moneyline_not_complete_close() -> None:
    row = dict(mod.parse_games((HEADER + ROWS).encode())[0])
    row["away_moneyline"] = ""
    assert mod._populated(row) is False


def test_bad_present_close_price_fails_closed(tmp_path: Path) -> None:
    rows = "2024_01_BAL_KC,2024,1,2024-09-05,BAL,KC,20,27,3,48.5,NaN,-175\n"
    with pytest.raises(ValueError, match="NFLVERSE_CLOSE_VALUE_INVALID"):
        mod.archive((HEADER + rows).encode(), tmp_path)


def test_bad_partial_row_still_fails_closed() -> None:
    row = dict(mod.parse_games((HEADER + ROWS).encode())[0])
    row["spread_line"] = ""
    row["home_moneyline"] = "-50"
    with pytest.raises(ValueError, match="NFLVERSE_CLOSE_PRICE_INVALID"):
        mod._populated(row)
