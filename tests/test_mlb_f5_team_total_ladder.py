import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import mlb_f5_team_total_ladder as m

T0 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _games(n, f5=2, reg=5, start=T0):
    return [{"game_id": str(i), "start": start + timedelta(days=i), "away_f5": f5, "home_f5": f5,
             "away_reg": reg, "home_reg": reg, "completed_innings": 9} for i in range(n)]


def test_f5_nb_plus_late_reproduces_full_game_nb():
    r, mu, s = m.V8_INDEPENDENT_TEAM_DISPERSION_R, 4.6, 0.55
    n, f5, tot = 60000, [0] * 40, [0] * 40
    import numpy as np
    g = np.random.default_rng(7)
    lam = g.gamma(r, mu / r, n)
    a, b = g.poisson(s * lam), g.poisson((1 - s) * lam)
    for x, y in zip(a, b):
        f5[min(x, 39)] += 1
        tot[min(x + y, 39)] += 1
    for emp, pmf in ((f5, m.nb_pmf(s * mu)), (tot, m.nb_pmf(mu))):
        assert max(abs(e / n - p) for e, p in zip(emp, pmf)) < 0.006


def test_ladder_two_sided_monotone_and_main_line():
    out = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.8, "f5_share": 0.55})
    assert out["main_line"] == 1.5 and out["play_authority"] is False
    for side in ("AWAY", "HOME"):
        lad = out["teams"][side]["ladder"]
        assert [x["line"] for x in lad] == [0.5, 1.5, 2.5, 3.5, 4.5]
        assert all(abs(x["over"] + x["under"] + x["push"] - 1) < 1e-12 and x["push"] == 0 for x in lad)
        assert all(lad[i]["over"] > lad[i + 1]["over"] for i in range(4))
    assert out["teams"]["HOME"]["ladder"][1]["over"] > out["teams"]["AWAY"]["ladder"][1]["over"]


def test_whole_line_push_mass():
    out = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.4, "f5_share": 0.55, "lines": [2]})
    row = out["teams"]["AWAY"]["ladder"][0]
    assert row["push"] > 0 and abs(row["over"] + row["under"] + row["push"] - 1) < 1e-12


def test_f5_game_total_not_offered_and_disabled_factors_rejected():
    for mk in ("F5_TOTALS", "F5_GAME_TOTAL"):
        assert m.price_f5_team_totals({"market": mk})["reason"] == "NOT_OFFERED_ON_DK"
    with pytest.raises(m.F5LadderError, match="disabled"):
        m.price_f5_team_totals({"away_mean_runs": 4, "home_mean_runs": 4, "f5_share": .5, "rest_adj": 0.1})


def test_settlement_push_tie_and_no_action():
    assert m.settle_f5_team_total(team_f5_runs=2, line=2, side="OVER", completed_innings=5) == "PUSH"
    assert m.settle_f5_team_total(team_f5_runs=2, line=1.5, side="OVER", completed_innings=9) == "WIN"
    assert m.settle_f5_team_total(team_f5_runs=1, line=1.5, side="OVER", completed_innings=9) == "LOSS"
    assert m.settle_f5_team_total(team_f5_runs=5, line=1.5, side="OVER", completed_innings=4.2) == "NO_ACTION"
    assert m.settle_either_pitcher_max(away_value=5, home_value=3, line=5, side="OVER") == "PUSH"
    assert m.settle_either_pitcher_max(away_value=7, home_value=3, line=5.5, side="UNDER") == "LOSS"


def test_share_is_point_in_time():
    games = _games(40)
    late = _games(40, f5=9, reg=9, start=T0 + timedelta(days=100))
    as_of = T0 + timedelta(days=50)
    a = m.fit_f5_share(games, as_of=as_of)
    assert a == m.fit_f5_share(list(reversed(games + late)), as_of=as_of)
    assert a["share"] == pytest.approx(0.4)
    with pytest.raises(m.F5LadderError):
        m.fit_f5_share(games, as_of=T0 + timedelta(days=10))


def test_either_pitcher_max_ladder():
    a, b = [0.2, 0.3, 0.5], [0.6, 0.4]
    out = m.either_pitcher_ladder(a, b, [0.5, 1, 1.5])
    # P(max <= 0) = .2*.6 ; P(max <= 1) = .5*1.0
    assert out["ladder"][0]["over"] == pytest.approx(1 - 0.12)
    assert out["ladder"][1]["push"] == pytest.approx(0.5 - 0.12)
    assert out["ladder"][2]["over"] == pytest.approx(0.5)
    assert out["status"] == "RESEARCH_ONLY" and out["play_authority"] is False


def _find(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _find(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _find(v, key)


def test_f5_markets_remain_ineligible_in_deployments():
    cfg = json.load(open("config/deployments.json"))
    for mk in ("F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"):
        hits = list(_find(cfg, mk))
        assert hits and all(h.get("eligible") is False for h in hits if isinstance(h, dict))
