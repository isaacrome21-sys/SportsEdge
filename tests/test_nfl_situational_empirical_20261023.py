"""NFL situational research engine: PIT, fail-closed, research-only."""
import math
import pytest

from sportsedge.nfl_situational_empirical import (
    GOVERNANCE, NflSituationalError, lead_over_under, price_situational)


def _g(date, season, home, away, hp, ap, first="H", lead=7, sh=0, sa=0, dh=0, da=0):
    return {"date": date, "season": season, "home": home, "away": away, "home_pts": hp,
            "away_pts": ap, "first_score": first, "largest_lead": lead, "safety_h": sh,
            "safety_a": sa, "dst_td_h": dh, "dst_td_a": da}


def _hist():
    rows = []
    for i in range(6):
        rows.append(_g(f"2023-10-{10 + i:02d}", 2023, "AAA", "BBB", 31, 10, "H", 21, 1, 0, 1, 0))
        rows.append(_g(f"2023-10-{10 + i:02d}", 2023, "CCC", "DDD", 17 + 3 * i, 14 + 2 * i, "A", 6))
        rows.append(_g(f"2023-11-{10 + i:02d}", 2023, "EEE", "FFF", 3 + 8 * i, 45 - 7 * i, "A", 9))
        rows.append(_g(f"2024-09-{10 + i:02d}", 2024, "BBB", "AAA", 7, 28, "A", 21, 0, 1, 0, 1))
        rows.append(_g(f"2024-09-{10 + i:02d}", 2024, "DDD", "CCC", 20, 20, "H", 3))
    return rows


def price(family, **kw):
    a = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")
    a.update(kw)
    return price_situational(_hist(), family=family, **a)


@pytest.mark.parametrize("fam,n", [("SAFETY", None), ("DST_TD", None), ("FIRST_SCORE", None),
                                   ("LARGEST_LEAD", None), ("BOTH_TEAMS_TO_SCORE_N", 20)])
def test_research_only_and_probabilities_valid(fam, n):
    p = price(fam, n=n)
    assert p["governance"] == GOVERNANCE and p["governance"]["play_allowed"] is False
    assert p["governance"]["validation_status"] == "NOT_VALIDATED"
    if "p_yes" in p:
        assert 0 < p["p_yes"] < 1
    if "probs" in p:
        assert math.isclose(sum(p["probs"].values()), 1.0)
    if "pmf" in p:
        assert math.isclose(sum(p["pmf"].values()), 1.0) and min(p["pmf"]) >= 0


def test_strong_team_more_likely_to_score_first():
    p = price("FIRST_SCORE")
    assert p["probs"]["home"] > p["probs"]["away"]


def test_safety_prone_matchup_rates_higher():
    assert price("SAFETY")["p_yes"] > price("SAFETY", home="CCC", away="DDD")["p_yes"]


def test_both_teams_monotone_in_n():
    ps = [price("BOTH_TEAMS_TO_SCORE_N", n=n)["p_yes"] for n in (10, 15, 20, 25, 30)]
    assert ps == sorted(ps, reverse=True)


def test_future_rows_do_not_leak():
    leak = _hist() + [_g("2024-10-02", 2024, "BBB", "AAA", 70, 0, "H", 70, 3, 3, 3, 3)]
    for fam, n in (("SAFETY", None), ("FIRST_SCORE", None), ("BOTH_TEAMS_TO_SCORE_N", 20)):
        assert price_situational(leak, family=fam, date="2024-10-01", season=2024,
                                 home="AAA", away="BBB", n=n) == price(fam, n=n)


@pytest.mark.parametrize("kw,msg", [
    ({"family": "FIRST_TD"}, "UNKNOWN_FAMILY"),
    ({"family": "BOTH_TEAMS_TO_SCORE_N", "n": 12}, "N_NOT_SUPPORTED"),
    ({"family": "BOTH_TEAMS_TO_SCORE_N", "n": True}, "N_NOT_SUPPORTED"),
    ({"family": "SAFETY", "n": 10}, "N_ONLY_FOR_BOTH_TEAMS"),
    ({"family": "SAFETY", "season": "2024"}, "SEASON_REQUIRED_INT"),
    ({"family": "SAFETY", "date": "2024/10/01"}, "GAME_DATE_INVALID"),
    ({"family": "SAFETY", "away": "AAA"}, "TEAMS_INVALID"),
    ({"family": "SAFETY", "home": "ZZZ"}, "TEAM_HISTORY_INSUFFICIENT"),
    ({"family": "SAFETY", "season": 2023, "date": "2023-11-01"}, "EMPTY_OUTCOME_POOL"),
])
def test_bad_inputs_refuse(kw, msg):
    fam = kw.pop("family")
    with pytest.raises(NflSituationalError, match=msg):
        price(fam, **kw)


@pytest.mark.parametrize("field,bad", [("home_pts", None), ("safety_h", "1"), ("largest_lead", -1),
                                       ("dst_td_a", 1.0), ("away_pts", True), ("first_score", "X")])
def test_malformed_history_refuses(field, bad):
    rows = _hist(); rows[0][field] = bad
    with pytest.raises(NflSituationalError):
        price_situational(rows, family="SAFETY", date="2024-10-01", season=2024, home="AAA", away="BBB")


def test_missing_field_refuses_not_zero_filled():
    rows = _hist(); del rows[1]["dst_td_h"]
    with pytest.raises(NflSituationalError, match="HISTORY_FIELD_MISSING"):
        price_situational(rows, family="DST_TD", date="2024-10-01", season=2024, home="AAA", away="BBB")


def test_lead_lines():
    p = price("LARGEST_LEAD")
    assert math.isclose(sum(lead_over_under(p, 13.5).values()), 1.0)
    for bad in ("13.5", True, float("nan"), 13.25, -1):
        with pytest.raises(NflSituationalError):
            lead_over_under(p, bad)
    with pytest.raises(NflSituationalError, match="NOT_LARGEST_LEAD"):
        lead_over_under(price("SAFETY"), 0.5)


def test_certain_outcome_refuses_instead_of_emitting_zero():
    rows = [dict(r, home_pts=10, away_pts=10) for r in _hist()]
    with pytest.raises(NflSituationalError, match="DEGENERATE_PROBABILITY"):
        price_situational(rows, family="BOTH_TEAMS_TO_SCORE_N", date="2024-10-01", season=2024,
                          home="AAA", away="BBB", n=30)
