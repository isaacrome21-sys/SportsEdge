"""NFL period-line research engine: PIT, fail-closed, research-only."""
import math
import pytest

from sportsedge.nfl_period_lines_empirical import (
    GOVERNANCE, NflPeriodLinesError, price_period, spread_probs, total_probs)


def _g(date, season, home, away, h, a):
    r = {"date": date, "season": season, "home": home, "away": away}
    for p in ("q1", "q2", "q3", "q4", "h1", "h2"):
        r[f"{p}_h"], r[f"{p}_a"] = h, a
    return r


def _hist():
    rows = []
    for i in range(8):
        rows.append(_g(f"2023-10-{10 + i:02d}", 2023, "AAA", "BBB", 7 + i % 3, 3))
        rows.append(_g(f"2023-10-{10 + i:02d}", 2023, "CCC", "DDD", 3, i % 2))
    for i in range(4):
        rows.append(_g(f"2024-09-{10 + i:02d}", 2024, "BBB", "AAA", 0, 10))
        rows.append(_g(f"2024-09-{10 + i:02d}", 2024, "DDD", "CCC", 3, 3))
    return rows


def price(**kw):
    a = dict(date="2024-10-01", season=2024, home="AAA", away="BBB", period="h1")
    a.update(kw)
    return price_period(_hist(), **a)


def test_governance_is_research_only():
    p = price()
    assert p["governance"] == GOVERNANCE
    assert p["governance"]["play_allowed"] is False
    assert p["governance"]["validation_status"] == "NOT_VALIDATED"


def test_pmfs_and_moneyline_sum_to_one():
    p = price()
    assert math.isclose(sum(p["margin_pmf"].values()), 1.0)
    assert math.isclose(sum(p["total_pmf"].values()), 1.0)
    assert math.isclose(sum(p["moneyline_3way"].values()), 1.0)
    assert min(p["total_pmf"]) >= 0


def test_strong_home_team_favoured():
    p = price()
    assert p["moneyline_3way"]["home"] > p["moneyline_3way"]["away"]


def test_future_games_do_not_leak():
    base = price()
    leak = _hist() + [_g("2024-10-05", 2024, "BBB", "AAA", 60, 0)]
    assert price_period(leak, date="2024-10-01", season=2024, home="AAA",
                        away="BBB", period="h1") == base


def test_outcome_pool_uses_only_earlier_seasons():
    rows = [r for r in _hist() if r["season"] == 2024]
    with pytest.raises(NflPeriodLinesError, match="EMPTY_OUTCOME_POOL"):
        price_period(rows, date="2024-10-01", season=2024, home="AAA", away="BBB", period="h1")


@pytest.mark.parametrize("kw,msg", [
    ({"period": "h3"}, "UNKNOWN_PERIOD"),
    ({"season": "2024"}, "SEASON_REQUIRED_INT"),
    ({"season": True}, "SEASON_REQUIRED_INT"),
    ({"date": "10/01/2024"}, "GAME_DATE_INVALID"),
    ({"home": "BBB"}, "TEAMS_INVALID"),
    ({"home": "ZZZ"}, "TEAM_HISTORY_INSUFFICIENT"),
])
def test_bad_inputs_refuse(kw, msg):
    with pytest.raises(NflPeriodLinesError, match=msg):
        price(**kw)


@pytest.mark.parametrize("bad", [None, "7", -1, 2.0, True])
def test_malformed_history_points_refuse(bad):
    rows = _hist(); rows[0]["h1_h"] = bad
    with pytest.raises(NflPeriodLinesError):
        price_period(rows, date="2024-10-01", season=2024, home="AAA", away="BBB", period="h1")


def test_missing_history_field_refuses():
    rows = _hist(); del rows[3]["h1_a"]
    with pytest.raises(NflPeriodLinesError, match="HISTORY_FIELD_MISSING"):
        price_period(rows, date="2024-10-01", season=2024, home="AAA", away="BBB", period="h1")


def test_line_probabilities_sum_to_one_and_push_only_on_integers():
    p = price()
    for ln in (3, 3.5, -3, -3.5, 0):
        assert math.isclose(sum(spread_probs(p, ln).values()), 1.0)
    assert total_probs(p, 10.5)["push"] == 0.0
    assert math.isclose(sum(total_probs(p, 10).values()), 1.0)


@pytest.mark.parametrize("bad", ["3.5", True, None, float("nan"), float("inf"), 3.25])
def test_bad_lines_refuse(bad):
    p = price()
    with pytest.raises(NflPeriodLinesError):
        total_probs(p, bad)
    with pytest.raises(NflPeriodLinesError):
        spread_probs(p, bad)
