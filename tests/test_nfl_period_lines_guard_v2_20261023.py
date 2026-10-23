"""v2 guard: quarter spreads |line|<=1 restate the refused moneyline; the private
pricer strips refused families unless explicitly allowed inside screen_only()."""
import pytest

from sportsedge import nfl_period_lines_empirical as E
from sportsedge.screen_only_guard import ScreenOnlyGuardError, screen_only
from tests.test_nfl_period_lines_empirical_20261023 import _hist

KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
@pytest.mark.parametrize("line", [0, 0.0, 0.5, -0.5, 1, -1, 1.0, -1.0])
def test_quarter_spread_within_one_point_refused(period, line):
    p = E.price_period(_hist(), period=period, **KW)
    with pytest.raises(E.NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_MONEYLINE"):
        E.spread_probs(p, line)


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
@pytest.mark.parametrize("line", [1.5, -1.5, 2, -3.5, 7])
def test_quarter_spread_beyond_one_point_prices(period, line):
    p = E.price_period(_hist(), period=period, **KW)
    assert sum(E.spread_probs(p, line).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("line", [0, 0.5, -1])
def test_half_spreads_near_zero_still_price(line):
    p = E.price_period(_hist(), period="h1", **KW)
    assert sum(E.spread_probs(p, line).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("period,ml_gone,total_gone", [
    ("q1", True, True), ("q2", True, False), ("q3", True, True), ("q4", True, True),
    ("h1", False, False), ("h2", False, False)])
def test_private_pricer_strips_refused_families(period, ml_gone, total_gone):
    out = E._price_period(_hist(), period=period, **KW)
    assert ("moneyline_3way" not in out) is ml_gone
    assert ("total_pmf" not in out) is total_gone
    assert "screen_only_unrestricted" not in out


def test_private_pricer_unrestricted_mode_requires_guard():
    with pytest.raises(ScreenOnlyGuardError, match="SCREEN_ONLY_GUARD"):
        E._price_period(_hist(), period="q1", allow_refused=True, **KW)
    with screen_only():
        assert "moneyline_3way" in E._price_period(_hist(), period="q1", allow_refused=True, **KW)


@pytest.mark.parametrize("bad", [1, "yes", None])
def test_allow_refused_must_be_bool(bad):
    with screen_only():
        with pytest.raises(E.NflPeriodLinesError, match="ALLOW_REFUSED_MUST_BE_BOOL"):
            E._price_period(_hist(), period="q1", allow_refused=bad, **KW)


def test_hand_built_output_without_refused_key_is_checked_by_period():
    with screen_only():
        raw = E.price_period_unrestricted(_hist(), period="q1", **KW)
    raw.pop("screen_only_unrestricted")
    with pytest.raises(E.NflPeriodLinesError, match="NAIVE_FAIL:Q1_MONEYLINE"):
        E.spread_probs(raw, 0)
