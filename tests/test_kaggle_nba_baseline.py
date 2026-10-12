"""Tests for sportsedge/backtest/kaggle_nba_baseline.py.

Synthetic normalized archive only. Verifies the BaselineSource contract:
no-vig math, fixture-id join, exact line matching, fail-closed codes,
contradictory-duplicate quarantine, and season-mismatch guards.
"""

import csv
from pathlib import Path

import pytest

from sportsedge.backtest.kaggle_nba_baseline import (
    KaggleNbaBaseline,
    american_pair_to_no_vig,
    american_to_decimal,
    no_vig_probs,
)

COLUMNS = ["game_date", "season_label", "home_team", "away_team",
           "home_score", "away_score", "closing_spread_home",
           "spread_home_juice", "spread_away_juice", "closing_total",
           "over_juice", "under_juice", "closing_ml_home", "closing_ml_away"]

GAME = {"game_date": "2025-11-05", "season_label": "2025",
        "home_team": "Boston Celtics", "away_team": "Philadelphia 76ers",
        "home_score": "120", "away_score": "110",
        "closing_spread_home": "-5.5", "spread_home_juice": "-110",
        "spread_away_juice": "-110", "closing_total": "224.5",
        "over_juice": "-110", "under_juice": "-110",
        "closing_ml_home": "-220", "closing_ml_away": "180"}

FIXTURE = "nba:2025-11-05:Philadelphia 76ers:Boston Celtics"


def _write_archive(root: Path, games):
    season_dir = root / "archive" / "nba-kaggle-odds" / "2025"
    season_dir.mkdir(parents=True, exist_ok=True)
    with (season_dir / "games.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(games)


@pytest.fixture()
def baseline(tmp_path):
    _write_archive(tmp_path, [GAME])
    return KaggleNbaBaseline(tmp_path).load()


def test_math_helpers():
    assert american_to_decimal(-110) == pytest.approx(1.9090909)
    assert american_to_decimal(150) == pytest.approx(2.5)
    with pytest.raises(Exception):
        american_to_decimal(-50)  # the -100/+100 gap is invalid
    hp, ap = american_pair_to_no_vig(-220, 180)
    assert hp == pytest.approx(0.6582, abs=1e-3)
    assert hp + ap == pytest.approx(1.0)


def test_ml_lookup_no_vig(baseline):
    prob = baseline.lookup(FIXTURE, "ML", "HOME")
    hp, _ = american_pair_to_no_vig(-220, 180)
    assert prob == pytest.approx(hp)
    away = baseline.lookup(FIXTURE, "ML", "AWAY")
    assert away == pytest.approx(1 - hp)


def test_ml_line_must_be_none(baseline):
    assert baseline.lookup(FIXTURE, "ML", "HOME", line=-5.5) is None
    assert "BASELINE_ML_LINE_MUST_BE_NONE" in baseline.explain(
        FIXTURE, "ML", "HOME", line=-5.5)


def test_spread_exact_line_match(baseline):
    prob = baseline.lookup(FIXTURE, "SPREAD", "HOME", line=-5.5)
    hp, _ = american_pair_to_no_vig(-110, -110)
    assert prob == pytest.approx(hp)
    # Away perspective is the mirror of the home line.
    away = baseline.lookup(FIXTURE, "SPREAD", "AWAY", line=5.5)
    assert away == pytest.approx(1 - hp)
    # Wrong line -> MISSING, never a nearby price.
    assert baseline.lookup(FIXTURE, "SPREAD", "HOME", line=-6.0) is None
    assert baseline.lookup(FIXTURE, "SPREAD", "HOME") is None


def test_total_lookup(baseline):
    over = baseline.lookup(FIXTURE, "TOTAL", "OVER", line=224.5)
    ovp, unp = american_pair_to_no_vig(-110, -110)
    assert over == pytest.approx(ovp)
    under = baseline.lookup(FIXTURE, "TOTAL", "UNDER", line=224.5)
    assert under == pytest.approx(unp)


def test_missing_juice_is_missing_not_invented(tmp_path):
    game = dict(GAME)
    game["spread_home_juice"] = ""
    game["spread_away_juice"] = ""
    _write_archive(tmp_path, [game])
    loader = KaggleNbaBaseline(tmp_path).load()
    assert loader.lookup(FIXTURE, "SPREAD", "HOME", line=-5.5) is None
    assert "BASELINE_SPREAD_QUOTE_INCOMPLETE" in loader.explain(
        FIXTURE, "SPREAD", "HOME", line=-5.5)
    # ML still works: only the juice-less leg is MISSING.
    assert loader.lookup(FIXTURE, "ML", "HOME") is not None


def test_unknown_game_is_missing(baseline):
    assert baseline.lookup(
        "nba:2025-11-05:Chicago Bulls:Miami Heat", "ML", "HOME") is None


def test_malformed_fixture_id_is_missing(baseline):
    assert baseline.lookup("nonsense", "ML", "HOME") is None


def test_contradictory_duplicate_quarantines_game(tmp_path):
    other = dict(GAME)
    other["closing_ml_home"] = "-200"  # same game, different price
    _write_archive(tmp_path, [GAME, other])
    loader = KaggleNbaBaseline(tmp_path).load()
    assert loader.stats["quarantined_games"] == 1
    assert loader.lookup(FIXTURE, "ML", "HOME") is None
    assert "BASELINE_GAME_QUARANTINED" in loader.explain(
        FIXTURE, "ML", "HOME")


def test_exact_duplicate_is_harmless(tmp_path):
    _write_archive(tmp_path, [GAME, dict(GAME)])
    loader = KaggleNbaBaseline(tmp_path).load()
    assert loader.stats["duplicate_rows"] == 1
    assert loader.lookup(FIXTURE, "ML", "HOME") is not None


def test_season_mismatch_row_skipped(tmp_path):
    game = dict(GAME)
    game["season_label"] = "2024"  # Nov 2025 cannot be season 2024
    _write_archive(tmp_path, [game])
    loader = KaggleNbaBaseline(tmp_path).load()
    assert loader.stats["rows_accepted"] == 0
    assert loader.stats["skip_reasons"][
        "BASELINE_KAGGLE_NBA_SEASON_MISMATCH"] == 1


def test_coverage_audit(baseline):
    cov = baseline.coverage()
    assert cov["source"] == "kaggle_nba"
    assert cov["rows_accepted"] == 1
    assert cov["seasons"] == {"2025": 1}
