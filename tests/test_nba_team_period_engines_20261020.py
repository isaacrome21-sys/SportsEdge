"""Tests for sportsedge/nba_team_period_engine.py — the Oct 18
calibration construction (B4 team totals; B11 quarter totals) as an
engine. Fixtures are synthetic and programmatic; expected values are
computed from the repo's own pinned machinery (ratings replay) or by
hand from the construction's formulas — never from the engine's own
outputs alone.
"""
from datetime import date, timedelta

import pytest

from sportsedge.nba_team_period_engine import (
    ENGINE_ID,
    NBATeamPeriodEngine,
    REFUSAL_INSUFFICIENT_LEAGUE_PRIORS,
    REFUSAL_INSUFFICIENT_TEAM_PRIORS,
    REFUSAL_PERIOD_FIT_HISTORY_MISSING,
    REFUSAL_PERIOD_HISTORY_UNAVAILABLE,
    REFUSAL_TEAM_NOT_IN_HISTORY,
    games_from_team_boxscores,
    price_game,
)
from sportsedge.sports.nba.ratings_model import replay

TEAMS = ["AAA", "BBB", "CCC", "DDD"]
PAIRINGS = [("AAA", "BBB"), ("CCC", "DDD"), ("AAA", "CCC"),
            ("BBB", "DDD"), ("AAA", "DDD"), ("BBB", "CCC"),
            ("BBB", "AAA"), ("DDD", "CCC"), ("CCC", "AAA"),
            ("DDD", "BBB"), ("DDD", "AAA"), ("CCC", "BBB")]


def _quarters(seed):
    return (20 + seed % 5, 22 + seed % 3, 21 + seed % 4, 23 + seed % 6)


def _game(gid, d, season, home, away, seed):
    hq, aq = _quarters(seed), _quarters(seed + 3)
    return {"game_id": gid, "date": d.isoformat(), "season": season,
            "home": home, "away": away,
            "home_pts": float(sum(hq)), "away_pts": float(sum(aq)),
            "home_quarters": hq, "away_quarters": aq}


def _fit_span_games():
    out = []
    for i in range(8):
        home, away = PAIRINGS[i]
        out.append(_game(f"fit-{i}", date(2014, 10, 28) + timedelta(days=3 * i),
                         2014, home, away, seed=100 + i))
    return out


def _season_games(n, start=date(2015, 10, 27)):
    out = []
    for i in range(n):
        home, away = PAIRINGS[i % len(PAIRINGS)]
        out.append(_game(f"s2015-{i}", start + timedelta(days=i // 2),
                         2015, home, away, seed=200 + i))
    return out


def _history(season_n=100):
    return _fit_span_games() + _season_games(season_n)


TARGET = {"home": "AAA", "away": "BBB", "season": 2015,
          "target_date": "2016-02-01"}


def test_price_game_team_totals_match_pinned_ratings_replay():
    hist = _history(100)
    out = price_game(hist, TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"],
                     period_source=("test_archive", "v1"))
    assert out["status"] == "PRICED"
    assert out["engine_id"] == ENGINE_ID
    assert out["sufficiency_met"] is True
    assert out["priors"] == {"home_team_games": 50, "away_team_games": 50,
                             "league_team_games": 200}
    prior = [g for g in hist if g["date"] < TARGET["target_date"]]
    state = replay(prior)
    hp, ap = state.predict(TARGET["home"], TARGET["away"])
    assert out["team_totals"] == {"home": hp, "away": ap}


def test_period_allocations_are_exact_shares_of_team_totals():
    out = price_game(_history(100), TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"],
                     period_source=("test_archive", "v1"))
    per = out["periods"]
    assert per["status"] == "PRICED"
    assert per["fit_version"].startswith("NBA_PERIOD_FIT_V1:")
    shares = per["quarter_shares"]
    assert sum(shares) == pytest.approx(1.0, abs=1e-12)
    hp, ap = out["team_totals"]["home"], out["team_totals"]["away"]
    for q in range(4):
        assert per["team_quarter_totals"]["home"][q] == pytest.approx(
            shares[q] * hp, abs=1e-9)
        assert per["game_quarter_totals"][q] == pytest.approx(
            per["team_quarter_totals"]["home"][q]
            + per["team_quarter_totals"]["away"][q], abs=1e-9)
    for h in range(2):
        assert per["team_half_totals"]["home"][h] == pytest.approx(
            per["team_quarter_totals"]["home"][2 * h]
            + per["team_quarter_totals"]["home"][2 * h + 1], abs=1e-9)
        assert per["game_half_totals"][h] == pytest.approx(
            (shares[2 * h] + shares[2 * h + 1]) * (hp + ap), abs=1e-9)


def test_period_shares_equal_hand_computed_fit_span_shares():
    games = _fit_span_games()
    eng = NBATeamPeriodEngine()
    params = eng.fit_periods(games, source="test_archive",
                             source_version="v1")
    tot = [0, 0, 0, 0]
    for g in games:
        for q in range(4):
            tot[q] += g["home_quarters"][q] + g["away_quarters"][q]
    expected = tuple(x / sum(tot) for x in tot)
    assert params.quarter_shares == pytest.approx(expected, abs=1e-15)
    # a later-season game with quarters must NOT enter the frozen fit
    later = _season_games(4)
    eng2 = NBATeamPeriodEngine()
    params2 = eng2.fit_periods(games + later, source="test_archive",
                               source_version="v1")
    assert params2.quarter_shares == params.quarter_shares
    assert params2.version == params.version


def test_future_same_day_and_target_game_injection_bit_identical():
    hist = _history(100)
    base = price_game(hist, TARGET["home"], TARGET["away"],
                      season=TARGET["season"],
                      target_date=TARGET["target_date"],
                      period_source=("test_archive", "v1"))
    poisoned = hist + [
        _game("future-1", date(2016, 3, 1), 2015, "AAA", "BBB", seed=999),
        _game("same-day", date(2016, 2, 1), 2015, "CCC", "DDD", seed=998),
        {"game_id": "the-target-itself", "date": "2016-02-01",
         "season": 2015, "home": "AAA", "away": "BBB",
         "home_pts": 200.0, "away_pts": 50.0,
         "home_quarters": (50, 50, 50, 50), "away_quarters": (10, 10, 10, 20)},
        _game("future-season", date(2016, 11, 1), 2016, "AAA", "BBB",
              seed=997),
    ]
    out = price_game(poisoned, TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"],
                     period_source=("test_archive", "v1"))
    assert out == base


def test_league_sufficiency_boundary():
    out = price_game(_history(99), TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"])
    assert out["status"] == "REFUSED"
    assert out["reason"] == REFUSAL_INSUFFICIENT_LEAGUE_PRIORS
    assert out["priors"]["league_team_games"] == 198


def test_team_sufficiency_boundary_and_history_reasons():
    hist = _history(100)
    eee_games = []
    for i in range(9):
        opp = TEAMS[i % 4]
        home, away = ("EEE", opp) if i % 2 == 0 else (opp, "EEE")
        eee_games.append(_game(f"eee-{i}", date(2015, 12, 1)
                               + timedelta(days=5 * i), 2015, home, away,
                               seed=500 + i))
    out = price_game(hist + eee_games, "EEE", "AAA", season=2015,
                     target_date="2016-02-01")
    assert out["status"] == "REFUSED"
    assert out["reason"] == REFUSAL_INSUFFICIENT_TEAM_PRIORS
    assert out["priors"]["home_team_games"] == 9
    eee_games.append(_game("eee-9", date(2016, 1, 20), 2015, "EEE", "BBB",
                            seed=509))
    out = price_game(hist + eee_games, "EEE", "AAA", season=2015,
                     target_date="2016-02-01")
    assert out["status"] == "PRICED"
    # a team seen only in the fit-span season: seen, but 0 in-season priors
    out = price_game(_fit_span_games() + _season_games(100), "CCC", "AAA",
                     season=2015, target_date="2016-02-01")
    assert out["status"] == "PRICED"  # CCC plays in-season too; control
    fit_only = [g for g in _fit_span_games() if "DDD" in (g["home"], g["away"])]
    other_season = [g for g in _season_games(100)
                    if "DDD" not in (g["home"], g["away"])]
    # DDD removed from the season: cannot reach league gate with 3 teams'
    # pairings absent, so assert the reason on a direct engine walk instead
    eng = NBATeamPeriodEngine()
    for g in sorted(fit_only + other_season,
                    key=lambda x: (x["date"], x["home"])):
        eng.consume(g)
    fc = eng.forecast("DDD", "AAA", season=2015, target_date="2016-02-01")
    assert fc["status"] == "REFUSED"
    assert fc["reason"] in (REFUSAL_INSUFFICIENT_TEAM_PRIORS,
                            REFUSAL_INSUFFICIENT_LEAGUE_PRIORS)
    assert fc["reason"] != REFUSAL_TEAM_NOT_IN_HISTORY
    out = price_game(hist, "ZZZ", "AAA", season=2015,
                     target_date="2016-02-01")
    assert out["status"] == "REFUSED"
    assert out["reason"] == REFUSAL_TEAM_NOT_IN_HISTORY


def test_period_fit_missing_and_unavailable_refusals():
    season_only = _season_games(110)
    out = price_game(season_only, TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"],
                     period_source=("test_archive", "v1"))
    assert out["status"] == "PRICED"
    assert out["periods"] == {"status": "REFUSED",
                              "reason": REFUSAL_PERIOD_FIT_HISTORY_MISSING}
    out = price_game(_history(100), TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"])
    assert out["status"] == "PRICED"
    assert out["periods"] == {"status": "REFUSED",
                              "reason": REFUSAL_PERIOD_HISTORY_UNAVAILABLE}


def _boxscore_rows(games, dates):
    rows = []
    for g in games:
        rows.append({"game_id": g["game_id"], "side": "home",
                     "team_tricode": g["home"], "points": int(g["home_pts"]),
                     "season": g["season"]})
        rows.append({"game_id": g["game_id"], "side": "away",
                     "team_tricode": g["away"], "points": int(g["away_pts"]),
                     "season": g["season"]})
        dates[g["game_id"]] = g["date"]
    return rows


def test_team_boxscore_adapter_and_no_data_period_path():
    raw = _fit_span_games() + _season_games(100)
    dates = {}
    rows = _boxscore_rows(raw, dates)
    games = games_from_team_boxscores(rows, dates)
    assert len(games) == len(raw)
    g0 = next(g for g in games if g["game_id"] == raw[0]["game_id"])
    assert g0["home"] == raw[0]["home"] and g0["away"] == raw[0]["away"]
    assert g0["home_quarters"] is None and g0["away_quarters"] is None
    # the maintained path carries no quarter scores anywhere: team
    # totals price, period forms refuse NO_DATA even with a fit request
    out = price_game(games, TARGET["home"], TARGET["away"],
                     season=TARGET["season"],
                     target_date=TARGET["target_date"],
                     period_source=("sportsdataverse_team_boxscores", "v1"))
    assert out["status"] == "PRICED"
    assert out["periods"]["status"] == "REFUSED"
    assert out["periods"]["reason"] == REFUSAL_PERIOD_FIT_HISTORY_MISSING
    # adapter fail-closed paths
    with pytest.raises(ValueError):
        games_from_team_boxscores(rows, {k: v for k, v in dates.items()
                                         if k != raw[0]["game_id"]})
    with pytest.raises(ValueError):
        games_from_team_boxscores(rows + [rows[0]], dates)
    with pytest.raises(ValueError):
        games_from_team_boxscores(rows[:-1], dates)


def test_malformed_history_fails_closed():
    bad = _history(4)
    bad[0] = {**bad[0], "home_pts": -3.0}
    with pytest.raises(ValueError):
        price_game(bad, "AAA", "BBB", season=2015, target_date="2016-02-01")
    bad2 = _history(4)
    bad2[0] = {k: v for k, v in bad2[0].items() if k != "away_pts"}
    with pytest.raises(ValueError):
        price_game(bad2, "AAA", "BBB", season=2015, target_date="2016-02-01")
