"""Tests for the NBA 2024-25 fit-only module. Synthetic fixtures, plus an optional
read-only check against the on-box 2024-25 cache that also proves no 2025-26 file
is opened. No scoring anywhere."""
import ast
import builtins
import io
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.research import nba_fit_2024_25 as M
from sportsedge.research.nba_fit_2024_25 import FitError

TEAMS = sorted(M.NBA_FRANCHISES)


def _row(eid, when, home, away, hp, ap):
    return {"id": str(eid), "date": when.strftime("%Y-%m-%dT%H:%MZ"),
            "teams": [{"abbr": home, "homeAway": "home", "score": hp},
                      {"abbr": away, "homeAway": "away", "score": ap}]}


def _write(d: Path, rows):
    d.mkdir(parents=True, exist_ok=True)
    for r in rows:
        (d / f"{r['id']}.json").write_text(json.dumps(r))
    return d


def _season(n_days=60, seed=0):
    rng = random.Random(seed)
    t0 = datetime(2024, 10, 22, 23, 30, tzinfo=timezone.utc)
    rows, eid = [], 1
    for day in range(n_days):
        teams = TEAMS[:]
        rng.shuffle(teams)
        for k in range(0, 10, 2):
            hp, ap = rng.randint(95, 130), rng.randint(95, 130)
            if hp == ap:
                hp += 1
            rows.append(_row(eid, t0 + timedelta(days=day, minutes=30 * k), teams[k], teams[k + 1], hp, ap))
            eid += 1
    return rows


def test_fit_runs_on_synthetic_fit_window(tmp_path):
    d = _write(tmp_path / "nba_cache", _season())
    games, man = M.load_fit_games(d)
    assert man["games"] == 300 and len(man["dataset_sha256"]) == 64
    art = M.fit_all(games)
    assert art["holdout_touched"] is False and art["scores"] is None
    assert art["status"] == "RESEARCH_ONLY" and art["validation"] == "NO_VALIDATION"
    for b in ("ML_B0_constant", "ML_B1_elo", "ML_B2_srs_logistic", "TOTAL_T0_league", "TOTAL_T1_rolling"):
        assert b in art["baselines"]
    assert not any(k in json.dumps(art).lower() for k in ("log_loss", "crps", "brier", "verdict"))


@pytest.mark.parametrize("name", ["nba_cache_q_2025_26", "nba_cache_2025-26", "x_202526",
                                  "nba_cache_players", "random_dir"])
def test_non_fit_sources_refused(tmp_path, name):
    d = _write(tmp_path / name, _season(3))
    with pytest.raises(FitError) as e:
        M.load_fit_games(d)
    assert e.value.code in ("NBA_FIT_HOLDOUT_PATH_FORBIDDEN", "NBA_FIT_SOURCE_NOT_ALLOWED")


def test_holdout_dir_refused_even_nested(tmp_path):
    with pytest.raises(FitError) as e:
        M.load_fit_games(tmp_path / "nba_cache_q_2025_26" / "nba_cache")
    assert e.value.code == "NBA_FIT_HOLDOUT_PATH_FORBIDDEN"


@pytest.mark.parametrize("when", [datetime(2025, 10, 22, 23, 30, tzinfo=timezone.utc),
                                  datetime(2025, 7, 1, 0, 0, tzinfo=timezone.utc),
                                  datetime(2024, 9, 30, 23, 59, tzinfo=timezone.utc)])
def test_out_of_window_game_in_allowed_dir_fails_closed(tmp_path, when):
    rows = _season(3) + [_row(99999, when, "BOS", "NY", 110, 100)]
    with pytest.raises(FitError) as e:
        M.load_fit_games(_write(tmp_path / "nba_cache", rows))
    assert e.value.code == "NBA_FIT_WINDOW_VIOLATION"


def test_fit_all_refuses_leaked_game_objects():
    games = [M.FitGame(str(i), datetime(2024, 11, 1, tzinfo=timezone.utc) + timedelta(hours=i),
                       "BOS", "NY", 110, 100) for i in range(150)]
    games.append(M.FitGame("leak", datetime(2025, 11, 1, tzinfo=timezone.utc), "BOS", "NY", 1, 0))
    with pytest.raises(FitError) as e:
        M.fit_all(games)
    assert e.value.code == "NBA_FIT_WINDOW_VIOLATION"


def test_exclusions_all_star_and_cup_final(tmp_path):
    t = datetime(2025, 2, 16, 20, 0, tzinfo=timezone.utc)
    rows = _season(3) + [_row(5001, t, "CHK", "SHQ", 41, 32),
                         _row(401734908, datetime(2024, 12, 18, 1, 30, tzinfo=timezone.utc),
                              "OKC", "MIL", 81, 97)]
    games, man = M.load_fit_games(_write(tmp_path / "nba_cache", rows))
    assert man["excluded"] == {"ALL_STAR_OR_CUP_FINAL": 2}
    assert all(g.event_id not in ("5001", "401734908") for g in games)


@pytest.mark.parametrize("mut,code", [
    (lambda r: r.update(date="2024-11-01T10:00"), "NBA_FIT_TIPOFF_NAIVE"),
    (lambda r: r.update(date="garbage"), "NBA_FIT_TIPOFF_INVALID"),
    (lambda r: r["teams"].pop(), "NBA_FIT_TEAMS_INVALID"),
    (lambda r: r["teams"][1].update(homeAway="home"), "NBA_FIT_HOME_AWAY_INVALID"),
    (lambda r: r["teams"][0].update(score=-1), "NBA_FIT_SCORE_INVALID"),
    (lambda r: r["teams"][0].update(score=float("nan")), "NBA_FIT_SCORE_INVALID"),
    (lambda r: r["teams"][0].update(score=100) or r["teams"][1].update(score=100), "NBA_FIT_TIED_FINAL"),
])
def test_malformed_rows_refused(tmp_path, mut, code):
    rows = _season(2)
    mut(rows[0])
    with pytest.raises(FitError) as e:
        M.load_fit_games(_write(tmp_path / "nba_cache", rows))
    assert e.value.code == code


def test_features_are_strictly_pregame(tmp_path):
    games, _ = M.load_fit_games(_write(tmp_path / "nba_cache", _season(20)))
    base = {f["event_id"]: f for f in M.pregame_features(games)}
    target = games[len(games) // 2]
    later = [g for g in games if g.tipoff > target.tipoff]
    mutated = [g if g.tipoff <= target.tipoff and g.event_id != target.event_id
               else M.FitGame(g.event_id, g.tipoff, g.home, g.away, g.home_pts + 50, g.away_pts)
               for g in games]
    again = {f["event_id"]: f for f in M.pregame_features(mutated)}
    assert again[target.event_id] == base[target.event_id]
    assert later


def test_same_tipoff_games_do_not_see_each_other():
    t = datetime(2024, 11, 1, 0, 0, tzinfo=timezone.utc)
    g1 = M.FitGame("a", t, "BOS", "NY", 120, 100)
    g2 = M.FitGame("b", t, "BOS", "MIA", 110, 100)   # impossible double-header, same stamp
    f = {x["event_id"]: x for x in M.pregame_features([g1, g2])}
    assert f["b"]["home_gp"] == 0


def test_module_source_never_names_holdout_paths():
    src = Path(M.__file__).read_text()
    tree = ast.parse(src)
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    allowed = set(M.FORBIDDEN_MARKERS)
    for c in consts:
        if c in allowed:
            continue
        assert "nba_cache_q_2025_26" not in c and "2025_26" not in c


REAL = Path("/workspace/nba_cache_q")


@pytest.mark.skipif(not REAL.is_dir(), reason="on-box 2024-25 cache not present (CI)")
def test_real_fit_cache_opens_no_2025_26_file(monkeypatch):
    opened = []
    real_open = io.open

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    real_listdir = os.listdir
    listed = []
    monkeypatch.setattr(os, "listdir", lambda p=".": listed.append(str(p)) or real_listdir(p))
    games, man = M.load_fit_games(REAL)
    art = M.fit_all(games)
    assert man["games"] == 1230 and man["excluded"] == {"ALL_STAR_OR_CUP_FINAL": 4}
    assert all("2025_26" not in p for p in opened + listed)
    assert art["holdout_touched"] is False and art["scores"] is None
