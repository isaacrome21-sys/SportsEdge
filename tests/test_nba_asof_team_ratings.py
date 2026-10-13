"""Leakage and determinism tests for as-of NBA team ratings.

Inputs are synthetic, deterministic unit-test games (not market or real
evidence); they exist only to exercise point-in-time behavior.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nba.asof_team_ratings import NBAGame, fit_asof, possessions
from sportsedge.sports.nba.asof_harness import run_harness

T0 = datetime(2024, 10, 22, 23, 0, tzinfo=timezone.utc)
TEAMS = [f"T{i:02d}" for i in range(10)]


def games(n_days=40, seed=7):
    rng = random.Random(seed)
    out = []
    for d in range(n_days):
        order = TEAMS[:]
        rng.shuffle(order)
        for k in range(0, 10, 2):
            h, a = order[k], order[k + 1]
            out.append(NBAGame(f"g{d:03d}{k}", T0 + timedelta(days=d, minutes=k), h, a,
                               100 + rng.randint(0, 25) + TEAMS.index(h),
                               100 + rng.randint(0, 25), 98 + rng.random() * 6,
                               98 + rng.random() * 6))
    return out


AS_OF = T0 + timedelta(days=20)


def _sig(r):
    return (r.games_used, r.league_pace, r.league_eff, r.hca,
            tuple(sorted(r.pace.items())), tuple(sorted(r.off.items())),
            tuple(sorted(r.deff.items())))


def test_shuffling_input_does_not_change_ratings():
    g = games()
    shuffled = g[:]
    random.Random(1).shuffle(shuffled)
    assert _sig(fit_asof(g, AS_OF)) == _sig(fit_asof(shuffled, AS_OF))


def test_adding_or_changing_future_games_does_not_change_ratings():
    g = games()
    base = _sig(fit_asof([x for x in g if x.start < AS_OF], AS_OF))
    assert _sig(fit_asof(g, AS_OF)) == base
    future = [NBAGame("fut" + str(i), AS_OF + timedelta(hours=i), "T00", "T01", 200, 50, 150, 150)
              for i in range(50)]
    assert _sig(fit_asof(g + future, AS_OF)) == base


def test_game_at_exact_as_of_is_excluded():
    g = games()
    at = NBAGame("at", AS_OF, "T00", "T01", 200, 50, 150, 150)
    assert _sig(fit_asof(g + [at], AS_OF)) == _sig(fit_asof(g, AS_OF))


def test_rest_adj_is_zero_and_prediction_uses_no_rest_term():
    r = fit_asof(games(), AS_OF)
    p = r.predict("T05", "T02")
    assert r.rest_adj == 0.0 and p["rest_adj"] == 0.0
    assert abs(p["margin"] - (p["home_points"] - p["away_points"])) < 1e-9


def test_fail_closed_inputs():
    with pytest.raises(ValueError, match="AS_OF_TIMEZONE_REQUIRED"):
        fit_asof(games(), AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="FEWER_THAN_30"):
        fit_asof(games(), T0 + timedelta(days=1))
    g = games()
    with pytest.raises(ValueError, match="DUPLICATE_GAME_ID"):
        fit_asof(g + [g[0]], AS_OF)
    with pytest.raises(ValueError, match="TEAM_HAS_NO_PRIOR_GAMES"):
        fit_asof(g, AS_OF).predict("T00", "NOPE")


def test_possessions_from_real_espn_box_shape():
    box = {"fieldGoalsMade-fieldGoalsAttempted": "42-83", "freeThrowsMade-freeThrowsAttempted": "22-25",
           "offensiveRebounds": "7", "totalTurnovers": "15", "turnovers": "15"}
    assert possessions(box) == pytest.approx(83 - 7 + 15 + 0.44 * 25)


def test_harness_is_walk_forward_and_reports_missing_market():
    rep = run_harness(games())
    assert rep["market_baseline"].startswith("MISSING")
    assert rep["MONEYLINE"]["n"] > 0 and rep["rest_adj"] == 0.0
    # Future-only perturbation of the last day cannot change earlier-day scores.
    g = games()
    last = max(x.start.date() for x in g)
    early = [x for x in g if x.start.date() < last]
    assert run_harness(early)["MONEYLINE"]["n"] < rep["MONEYLINE"]["n"]
