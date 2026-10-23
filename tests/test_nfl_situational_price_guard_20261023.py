"""t247: the NAIVE_FAIL refusal lives inside _price itself, so no internal path skips it."""
import pytest

from sportsedge import nfl_situational_empirical as E
from sportsedge.screen_only_guard import ScreenOnlyGuardError, screen_only
from tests.test_nfl_situational_empirical_20261023 import _hist

KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")
REFUSED = [("LARGEST_LEAD", None, "NAIVE_FAIL:LARGEST_LEAD"),
           ("BOTH_TEAMS_TO_SCORE_N", 10, "NAIVE_FAIL:BOTH_TEAMS_TO_SCORE_N_10")]


@pytest.mark.parametrize("family,n,code", REFUSED)
def test_private_price_refuses_naive_fail_by_default(family, n, code):
    with pytest.raises(E.NflSituationalError, match=code):
        E._price(_hist(), family=family, n=n, **KW)


@pytest.mark.parametrize("family,n,code", REFUSED)
def test_private_price_refuses_even_inside_guard_without_flag(family, n, code):
    with screen_only():
        with pytest.raises(E.NflSituationalError, match=code):
            E._price(_hist(), family=family, n=n, **KW)


@pytest.mark.parametrize("family,n,code", REFUSED)
def test_allow_refused_requires_guard(family, n, code):
    with pytest.raises(ScreenOnlyGuardError, match="SCREEN_ONLY_GUARD"):
        E._price(_hist(), family=family, n=n, allow_refused=True, **KW)


@pytest.mark.parametrize("bad", [1, 0, "yes", None])
def test_allow_refused_must_be_bool(bad):
    with pytest.raises(E.NflSituationalError, match="ALLOW_REFUSED_MUST_BE_BOOL"):
        E._price(_hist(), family="LARGEST_LEAD", allow_refused=bad, **KW)


@pytest.mark.parametrize("family,n,code", REFUSED)
def test_allow_refused_inside_guard_prices(family, n, code):
    with screen_only():
        out = E._price(_hist(), family=family, n=n, allow_refused=True, **KW)
    assert out["governance"]["play_allowed"] is False


def test_private_price_still_prices_passing_family():
    out = E._price(_hist(), family="BOTH_TEAMS_TO_SCORE_N", n=25, **KW)
    assert 0 < out["p_yes"] < 1
