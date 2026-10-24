"""NFL team defense counts research engine: PIT, fail-closed, research-only."""
import math
import pytest

from sportsedge.nfl_team_defense_counts_empirical import (
    GOVERNANCE, NflTeamDefenseError, over_under, price_team_count)


def _r(date, season, team, opp, sacks, to):
    return {"date": date, "season": season, "team": team, "opp": opp, "sacks": sacks, "turnovers": to}


def _hist():
    rows = []
    for i in range(6):
        d = f"2024-09-{10 + i:02d}"
        rows += [_r(d, 2024, "AAA", "BBB", 5, 0), _r(d, 2024, "BBB", "AAA", 1, 3),
                 _r(d, 2024, "CCC", "DDD", 2, 1), _r(d, 2024, "DDD", "CCC", 2, 1)]
    return rows


def price(**kw):
    a = dict(family="TEAM_SACKS", date="2024-10-01", season=2024, team="AAA", opp="BBB")
    a.update(kw)
    return price_team_count(_hist(), **a)


def test_governance_research_only_and_pmf_sums():
    p = price()
    assert p["governance"] == GOVERNANCE and p["governance"]["play_allowed"] is False
    assert math.isclose(sum(p["pmf"]), 1.0)


def test_strong_pass_rush_vs_leaky_line_rates_higher():
    assert price()["lambda"] > price(team="CCC", opp="DDD")["lambda"]


def test_future_rows_do_not_leak():
    leak = _hist() + [_r("2024-10-02", 2024, "AAA", "BBB", 15, 9)]
    assert price_team_count(leak, family="TEAM_SACKS", date="2024-10-01", season=2024,
                            team="AAA", opp="BBB") == price()


@pytest.mark.parametrize("kw,msg", [
    ({"family": "TEAM_PUNTS"}, "UNKNOWN_FAMILY"),
    ({"season": "2024"}, "SEASON_REQUIRED_INT"),
    ({"date": "2024/10/01"}, "GAME_DATE_INVALID"),
    ({"opp": "AAA"}, "TEAMS_INVALID"),
    ({"team": "ZZZ"}, "TEAM_HISTORY_INSUFFICIENT"),
    ({"date": "2024-09-01"}, "EMPTY_LEAGUE_POOL"),
])
def test_bad_inputs_refuse(kw, msg):
    with pytest.raises(NflTeamDefenseError, match=msg):
        price(**kw)


@pytest.mark.parametrize("bad", [None, "3", -1, 2.5, True])
def test_malformed_counts_refuse(bad):
    rows = _hist(); rows[0]["sacks"] = bad
    with pytest.raises(NflTeamDefenseError):
        price_team_count(rows, family="TEAM_SACKS", date="2024-10-01", season=2024, team="AAA", opp="BBB")


def test_missing_field_refuses_not_zero_filled():
    rows = _hist(); del rows[2]["turnovers"]
    with pytest.raises(NflTeamDefenseError, match="HISTORY_FIELD_MISSING"):
        price_team_count(rows, family="TEAM_TURNOVERS", date="2024-10-01", season=2024, team="AAA", opp="BBB")


def test_over_under_sums_and_refuses_bad_lines():
    p = price()
    assert math.isclose(sum(over_under(p, 2.5).values()), 1.0) and over_under(p, 2.5)["push"] == 0
    for bad in ("2.5", True, float("nan"), 2.25, -0.5):
        with pytest.raises(NflTeamDefenseError):
            over_under(p, bad)
