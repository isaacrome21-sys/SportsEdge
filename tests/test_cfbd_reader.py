"""Tests for sportsedge.cfbd_reader. Synthetic fixtures only.

No network, no API key, no real data. Verifies: game pairing, the
SRS-style opponent adjustment (fixed-point self-consistency, as-of
chronology, FCS exclusion), and the factor-coverage audit.
"""

import json
from pathlib import Path

import pytest

from sportsedge.cfbd_reader import (
    CFBDArchiveReader,
    CFBDReaderError,
    SCHEMA_VERSION,
)


def _season_file(root: Path, year: int, teams):
    path = root / "archive" / "cfb-advanced" / "seasons" / str(year)
    path.mkdir(parents=True, exist_ok=True)
    (path / "season_advanced.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "ARCHIVED",
        "rows": [{"team": t, "offense": {}, "defense": {}} for t in teams],
    }))


def _team_row(gid, team, home_team, off, deff):
    return {"id": gid, "team": team, "homeTeam": home_team,
            "offense": {"epaPerPlay": off},
            "defense": {"epaPerPlay": deff}}


def _week_file(root: Path, year: int, week: int, games):
    """games: list of (home, away, home_off, home_def, away_off, away_def)."""
    path = root / "archive" / "cfb-advanced" / "weeks" / str(year)
    path.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (home, away, ho, hd, ao, ad) in enumerate(games, start=1):
        rows.append(_team_row(i, home, home, ho, hd))
        rows.append(_team_row(i, away, home, ao, ad))
    (path / ("week_%02d.json" % week)).write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "ARCHIVED",
        "game_advanced": rows,
        "ppa_games": [],
    }))


@pytest.fixture()
def archive(tmp_path):
    root = tmp_path / "data"
    _season_file(root, 2025, ["Alpha", "Beta", "Gamma", "Delta"])
    # Week 1: Alpha hosts Beta; Gamma hosts Delta.
    _week_file(root, 2025, 1, [
        ("Alpha", "Beta", 0.30, 0.10, -0.05, 0.25),
        ("Gamma", "Delta", -0.20, 0.35, 0.40, -0.10),
    ])
    # Week 2: Alpha hosts Delta; Beta hosts FCS Team (excluded from graph).
    _week_file(root, 2025, 2, [
        ("Alpha", "Delta", 0.10, 0.20, 0.15, 0.05),
        ("Beta", "FCS Opponent", 0.50, -0.20, -0.40, 0.60),
    ])
    return root


def test_archived_weeks(archive):
    reader = CFBDArchiveReader(archive)
    assert reader.archived_weeks(2025) == [1, 2]
    assert reader.archived_weeks(2024) == []


def test_opponent_adjusted_as_of(archive):
    reader = CFBDArchiveReader(archive)
    result = reader.opponent_adjusted(2025, through_week=2)
    # Only week 1 counts (strictly before through_week).
    assert result.coverage["games_used"] == 2
    assert result.coverage["weeks_used"] == [1]
    assert set(result.teams) == {"Alpha", "Beta", "Gamma", "Delta"}
    for team, metrics in result.teams.items():
        assert metrics["games"] == 1
        assert metrics["adj_margin_epa"] == pytest.approx(
            metrics["adj_off_epa"] - metrics["adj_def_epa_allowed"])


def test_adjustment_satisfies_normal_equations(archive):
    """The solution must satisfy A^T(Ax - b) = 0 (least-squares defining
    property) and the zero-sum margin pinning. Rebuilds the design matrix
    independently in the test."""
    import numpy as np

    reader = CFBDArchiveReader(archive)
    result = reader.opponent_adjusted(2025, through_week=3)
    teams = result.teams
    assert result.coverage["games_used"] == 3  # FCS game excluded
    assert result.coverage["skipped"]["non_fbs_opponent"] == 1
    names = sorted(teams)
    index = {t: i for i, t in enumerate(names)}
    n = len(names)
    # Fixture games (week 1 and 2; FCS game excluded from the graph).
    games = [
        ("Alpha", "Beta", 0.30, 0.10, -0.05, 0.25),
        ("Gamma", "Delta", -0.20, 0.35, 0.40, -0.10),
        ("Alpha", "Delta", 0.10, 0.20, 0.15, 0.05),
    ]
    rows, targets = [], []
    for home, away, ho, hd, ao, ad in games:
        for team, opp, off, deff in ((home, away, ho, hd),
                                     (away, home, ao, ad)):
            ti, oi = index[team], index[opp]
            r = [0.0] * (2 * n)
            r[ti] = 1.0
            r[n + oi] = 1.0
            rows.append(r)
            targets.append(off)
            r = [0.0] * (2 * n)
            r[n + ti] = 1.0
            r[oi] = 1.0
            rows.append(r)
            targets.append(deff)
    a = np.array(rows)
    b = np.array(targets)
    x = np.array([teams[t]["adj_off_epa"] for t in names]
                 + [teams[t]["adj_def_epa_allowed"] for t in names])
    grad = a.T @ (a @ x - b)
    assert np.allclose(grad, 0.0, atol=1e-8), grad
    # Zero-sum pinning: mean adjusted margin == mean raw margin.
    raw_margins = [teams[t]["raw_off_epa"] - teams[t]["raw_def_epa_allowed"]
                   for t in names]
    adj_margins = [teams[t]["adj_margin_epa"] for t in names]
    assert sum(adj_margins) / n == pytest.approx(sum(raw_margins) / n)
    # This small fixture's game graph is bipartite -> the O/D split carries
    # gauge freedom; only margins are identified. The audit must say so.
    assert result.coverage["game_graph_components"] == 1
    assert result.coverage["offense_defense_split_identified"] is False
    assert "CFBD_ADJUST_SPLIT_GAUGE_FREEDOM" in result.coverage["warning"]


def test_no_games_fails_closed_with_reason(archive):
    reader = CFBDArchiveReader(archive)
    result = reader.opponent_adjusted(2025, through_week=1)
    assert result.teams == {}
    assert result.coverage["reason"] == "CFBD_ADJUST_NO_GAMES"
    assert result.coverage["games_used"] == 0


def test_deterministic(archive):
    reader = CFBDArchiveReader(archive)
    first = reader.opponent_adjusted(2025, through_week=3)
    second = reader.opponent_adjusted(2025, through_week=3)
    assert first.teams == second.teams


def test_missing_week_file_fails_closed(tmp_path):
    root = tmp_path / "data"
    _season_file(root, 2025, ["Alpha"])
    reader = CFBDArchiveReader(root)
    with pytest.raises(CFBDReaderError):
        reader.load_week(2025, 9)


def test_factor_coverage_audit(archive):
    reader = CFBDArchiveReader(archive)
    audit = reader.factor_coverage_audit(2025, through_week=3)
    assert audit["archive_status"] == "OK"
    assert audit["factors"]["cfbd_raw_epa"]["status"] == "VERIFIED_USED"
    assert audit["factors"]["cfbd_opponent_adjusted_epa"]["status"] == \
        "VERIFIED_USED"
    assert audit["factors"]["cfbd_sp_plus"]["status"] == "NOT_WIRED"


def test_factor_coverage_audit_empty(archive):
    reader = CFBDArchiveReader(archive)
    audit = reader.factor_coverage_audit(2024, through_week=3)
    assert audit["archive_status"].startswith("UNAVAILABLE")
    assert audit["factors"]["cfbd_raw_epa"]["status"] == "MISSING"
