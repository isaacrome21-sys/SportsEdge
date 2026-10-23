"""Screen-only guard on the unrestricted period pricer; ±0.5 quarter spreads refused
where the quarter moneyline is NAIVE_FAIL (a ±0.5 spread is a moneyline restated)."""
import pytest

from sportsedge.nfl_period_lines_empirical import (
    NflPeriodLinesError, price_period, price_period_unrestricted, spread_probs)
from sportsedge.screen_only_guard import ScreenOnlyGuardError, screen_only
from tests.test_nfl_period_lines_empirical_20261023 import _hist

KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")


def test_unrestricted_refuses_outside_guard():
    with pytest.raises(ScreenOnlyGuardError, match="SCREEN_ONLY_GUARD"):
        price_period_unrestricted(_hist(), period="q1", **KW)


def test_unrestricted_inside_guard_then_resets():
    with screen_only():
        assert "moneyline_3way" in price_period_unrestricted(_hist(), period="q1", **KW)
    with pytest.raises(ScreenOnlyGuardError):
        price_period_unrestricted(_hist(), period="q1", **KW)


def test_pricing_entry_point_needs_no_guard():
    assert "margin_pmf" in price_period(_hist(), period="h1", **KW)


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
@pytest.mark.parametrize("line", [0.5, -0.5])
def test_half_point_quarter_spread_refused(period, line):
    p = price_period(_hist(), period=period, **KW)
    with pytest.raises(NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_MONEYLINE"):
        spread_probs(p, line)


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
@pytest.mark.parametrize("line", [1.5, -1.5, 0, 3.5, -7])
def test_other_quarter_spreads_still_price(period, line):
    p = price_period(_hist(), period=period, **KW)
    assert sum(spread_probs(p, line).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("line", [0.5, -0.5])
def test_half_point_half_spread_prices(line):
    p = price_period(_hist(), period="h1", **KW)
    assert sum(spread_probs(p, line).values()) == pytest.approx(1.0)
