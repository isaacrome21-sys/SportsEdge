"""LARGEST_LEAD and BOTH_TEAMS_TO_SCORE_N n=10 lost to naive: coded refusal; guarded screen pricer."""
import json
from pathlib import Path

import pytest

from sportsedge.nfl_situational_empirical import (
    NAIVE_FAIL_FAMILIES, NflSituationalError, price_situational,
    price_situational_unrestricted)
from sportsedge.screen_only_guard import ScreenOnlyGuardError, screen_only
from tests.test_nfl_situational_empirical_20261023 import _hist

ROOT = Path(__file__).resolve().parents[1]
KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")


def test_naive_fail_set_matches_screen_failures():
    res = json.loads((ROOT / "research" / "grok_nfl_situational_screen_20261023" /
                      "screen_results_v2.json").read_text())
    worse = {k for k, v in res["families"].items() if v["verdict"] == "SCREEN_WORSE_THAN_NAIVE"}
    assert NAIVE_FAIL_FAMILIES == frozenset(worse) == frozenset({"LARGEST_LEAD", "BOTH_TEAMS_TO_SCORE_N_10"})


def test_largest_lead_refuses():
    with pytest.raises(NflSituationalError, match="NAIVE_FAIL:LARGEST_LEAD"):
        price_situational(_hist(), family="LARGEST_LEAD", **KW)


def test_both_teams_10_refuses_but_others_price():
    with pytest.raises(NflSituationalError, match="NAIVE_FAIL:BOTH_TEAMS_TO_SCORE_N_10"):
        price_situational(_hist(), family="BOTH_TEAMS_TO_SCORE_N", n=10, **KW)
    for n in (15, 20, 25, 30):
        assert 0 < price_situational(_hist(), family="BOTH_TEAMS_TO_SCORE_N", n=n, **KW)["p_yes"] < 1


def test_unrestricted_refuses_outside_screen_guard():
    with pytest.raises(ScreenOnlyGuardError, match="SCREEN_ONLY_GUARD"):
        price_situational_unrestricted(_hist(), family="LARGEST_LEAD", **KW)


def test_unrestricted_works_inside_guard_and_guard_resets():
    with screen_only():
        p = price_situational_unrestricted(_hist(), family="LARGEST_LEAD", **KW)
        assert p["screen_only_unrestricted"] is True and p["governance"]["play_allowed"] is False
    with pytest.raises(ScreenOnlyGuardError):
        price_situational_unrestricted(_hist(), family="LARGEST_LEAD", **KW)


def test_guard_resets_after_exception():
    with pytest.raises(ZeroDivisionError):
        with screen_only():
            1 / 0
    with pytest.raises(ScreenOnlyGuardError):
        price_situational_unrestricted(_hist(), family="SAFETY", **KW)


def test_guard_cannot_be_satisfied_by_a_truthy_flag(monkeypatch):
    import sportsedge.screen_only_guard as g
    tok = g._ACTIVE.set(1)
    try:
        with pytest.raises(ScreenOnlyGuardError):
            price_situational_unrestricted(_hist(), family="SAFETY", **KW)
    finally:
        g._ACTIVE.reset(tok)
