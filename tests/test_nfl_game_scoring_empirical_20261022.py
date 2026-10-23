import json
import math
from pathlib import Path

import pytest

from sportsedge import nfl_game_scoring_empirical as E
from sportsedge.canonical_coverage import resolve_market

ROOT = Path(__file__).resolve().parents[1]


def hist(n_weeks=6, season=2024):
    rows = []
    teams = ["AAA", "BBB", "CCC", "DDD"]
    for w in range(n_weeks):
        for i in range(0, 4, 2):
            h, a = teams[(i + w) % 4], teams[(i + 1 + w) % 4]
            rows.append({"game_id": f"{season}_{w}_{h}", "season": season,
                         "date": f"{season}-09-{10 + w:02d}", "home": h, "away": a,
                         "home_td": 4 if h == "AAA" else 2, "away_td": 4 if a == "AAA" else 1,
                         "home_pts": 30 if h == "AAA" else 17, "away_pts": 28 if a == "AAA" else 10})
    return rows


def test_pmfs_sum_to_one_and_strong_offense_higher():
    out = E.price_tds(hist(), home="AAA", away="BBB", season=2024, date="2024-10-30")
    for k in ("home_td_pmf", "away_td_pmf", "total_td_pmf"):
        assert math.fsum(out[k]) == pytest.approx(1.0)
    assert out["lambda_home"] > out["lambda_away"]
    assert out["play_allowed"] is False and out["state"] == "SCREEN"


def test_point_in_time_ignores_same_day_and_future():
    h = hist()
    a = E.price_tds(h, home="AAA", away="BBB", season=2024, date="2024-09-14")
    fut = h + [{"game_id": "F", "season": 2024, "date": "2024-09-14", "home": "BBB", "away": "AAA",
                "home_td": 9, "away_td": 0, "home_pts": 63, "away_pts": 0}]
    assert E.price_tds(fut, home="AAA", away="BBB", season=2024, date="2024-09-14") == a


@pytest.mark.parametrize("kw,code", [
    ({"home": "ZZZ"}, "TEAM_HISTORY_INSUFFICIENT"),
    ({"date": "2024-09-10"}, "EMPTY_LEAGUE_POOL"),
    ({"date": "bad"}, "GAME_DATE_REQUIRED"),
])
def test_fail_closed(kw, code):
    args = {"home": "AAA", "away": "BBB", "season": 2024, "date": "2024-10-30", **kw}
    with pytest.raises(E.NflGameScoringError, match=code):
        E.price_tds(hist(), **args)


@pytest.mark.parametrize("line", [2.0, -0.5, float("nan")])
def test_p_over_refuses_non_half_lines(line):
    with pytest.raises(E.NflGameScoringError):
        E.p_over([1.0] + [0.0] * E.MAX_TD, line)


def test_margin_bands_partition():
    probs = E.margin_band_probs(3.0, [float(x % 21 - 10) for x in range(300)])
    assert math.fsum(probs.values()) == pytest.approx(1.0)
    assert all(v > 0 for v in probs.values())


def test_race_fit_and_probs():
    train = [(x / 10.0, 1 if x > 0 else 0) for x in range(-100, 100) if x % 3]
    train += [(0.5, 0), (-0.5, 1)]
    fit = E.fit_race(train)
    p = E.race_probs(5.0, fit, 0.1)
    assert math.fsum(p.values()) == pytest.approx(1.0) and p["H"] > p["A"]
    with pytest.raises(E.NflGameScoringError):
        E.fit_race(train[:50])
    with pytest.raises(E.NflGameScoringError):
        E.race_probs(0.0, fit, 1.0)


def test_governance_and_screen_artifacts():
    cfg = json.loads((ROOT / "config/grok_nfl_game_scoring_research_v1.json").read_text())
    assert cfg["play_allowed"] is False and cfg["eligible"] is False
    assert cfg["state"] in ("SCREEN", "RESEARCH_UNSCREENED")
    res = json.loads((ROOT / "research/grok_nfl_game_scoring_screen_20261022/screen_results_v1.json").read_text())
    assert res["label"] == "SCREEN"
    for name in ("team_total", "total_touchdowns", "winning_margin_band", "race_to_n_points"):
        assert resolve_market("NFL", name)["state"] == "BLOCKED"
