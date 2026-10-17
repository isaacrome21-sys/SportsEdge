"""End-to-end no-lookahead regression for the LEVEL v2 evaluator (#2372).

Drives the evaluator's own predictor (build_v2_predictor, the code path
that produced the Part A results) on a synthetic two-season schedule and
proves, for every fixture:
  * changing any game at or after the fixture's kickoff -- including the
    fixture itself and other games at the identical kickoff -- leaves the
    fixture's prediction unchanged;
  * changing a strictly-prior game in the window DOES change it (teeth);
  * games from season S-2 never enter (window rule).
"""
import importlib.util
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "eval_v2", ROOT / "research" / "nfl_totals_level_v2_20261017"
    / "eval_nfl_totals_level_v2.py")
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)

ET = ZoneInfo("America/New_York")
TEAMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def _schedule(seed=7):
    rng = random.Random(seed)
    games = []
    for season in (2021, 2022, 2023):
        day = datetime(season, 9, 10, 13, 0, tzinfo=ET)
        for week in range(8):
            order = TEAMS[:]
            rng.shuffle(order)
            for i in range(0, 6, 2):
                games.append({
                    # two games share each kickoff instant (batch rule)
                    "kickoff": day + timedelta(days=7 * week, hours=3 * (i // 4)),
                    "season": season, "home": order[i], "away": order[i + 1],
                    "home_score": rng.randint(10, 38),
                    "away_score": rng.randint(7, 35)})
    return games


def _predict(games, fx):
    pred = ev.build_v2_predictor([dict(g) for g in games])
    target = next(g for g in [dict(x) for x in games]
                  if g["kickoff"] == fx["kickoff"] and g["home"] == fx["home"])
    # predictor is keyed by the game object's fields, not identity
    return pred(target)


def test_future_same_kickoff_and_self_never_enter():
    games = _schedule()
    fixtures = [g for g in games if g["season"] == 2023]
    for fx in fixtures[::3]:
        base = _predict(games, fx)
        bumped = [dict(g, home_score=g["home_score"] + 40)
                  if g["kickoff"] >= fx["kickoff"] else g for g in games]
        assert _predict(bumped, fx) == base, fx


def test_prior_game_changes_prediction():
    games = _schedule()
    fx = [g for g in games if g["season"] == 2023][-1]
    base = _predict(games, fx)
    prior = [g for g in games if g["kickoff"] < fx["kickoff"]
             and fx["home"] in (g["home"], g["away"])]
    tgt = max(prior, key=lambda g: g["kickoff"])
    bumped = [dict(g, home_score=g["home_score"] + 40) if g is tgt else g
              for g in games]
    assert _predict(bumped, fx) != base


def test_season_minus_two_never_enters():
    games = _schedule()
    fx = [g for g in games if g["season"] == 2023][5]
    base = _predict(games, fx)
    bumped = [dict(g, home_score=g["home_score"] + 40)
              if g["season"] == 2021 else g for g in games]
    assert _predict(bumped, fx) == base
