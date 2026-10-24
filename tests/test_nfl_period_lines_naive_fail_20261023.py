"""Families that lost to naive in the v1 screen must refuse with NAIVE_FAIL."""
import pytest

from sportsedge.nfl_period_lines_empirical import (
    NAIVE_FAIL_FAMILIES, NflPeriodLinesError, price_period, price_period_unrestricted,
    spread_probs, total_probs)
from tests.test_nfl_period_lines_empirical_20261023 import _hist

KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")


def test_declared_naive_fail_set_matches_v1_screen_failures():
    import json
    from pathlib import Path
    res = json.loads((Path(__file__).resolve().parents[1] / "research" /
                      "grok_nfl_period_lines_screen_20261023" / "screen_results_v1.json").read_text())
    worse = {k for k, v in res["families"].items() if v["verdict"] == "SCREEN_WORSE_THAN_NAIVE"}
    assert NAIVE_FAIL_FAMILIES == frozenset(worse)
    assert NAIVE_FAIL_FAMILIES == frozenset({"Q1_MONEYLINE", "Q2_MONEYLINE", "Q3_MONEYLINE",
                                             "Q4_MONEYLINE", "Q1_TOTAL", "Q3_TOTAL", "Q4_TOTAL"})


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
def test_quarter_moneyline_refused(period):
    p = price_period(_hist(), period=period, **KW)
    assert "moneyline_3way" not in p
    assert p["refused"]["moneyline"] == f"NAIVE_FAIL:{period.upper()}_MONEYLINE"


@pytest.mark.parametrize("period", ["q1", "q3", "q4"])
def test_failed_quarter_totals_refuse(period):
    p = price_period(_hist(), period=period, **KW)
    assert "total_pmf" not in p
    with pytest.raises(NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_TOTAL"):
        total_probs(p, 10.5)


@pytest.mark.parametrize("period", ["h1", "h2", "q2"])
def test_non_failed_totals_still_price(period):
    p = price_period(_hist(), period=period, **KW)
    assert sum(total_probs(p, 10.5).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("period", ["h1", "h2"])
def test_half_spreads_not_refused(period):
    p = price_period(_hist(), period=period, **KW)
    assert sum(spread_probs(p, -1.5).values()) == pytest.approx(1.0)


@pytest.mark.parametrize("period", ["q1", "q2", "q3", "q4"])
def test_quarter_spreads_refused_derivable(period):
    # Grok ruling 2026-10-23 Option 1.
    p = price_period(_hist(), period=period, **KW)
    with pytest.raises(NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_MONEYLINE_DERIVABLE"):
        spread_probs(p, -1.5)


def test_halves_keep_moneyline():
    assert "moneyline_3way" in price_period(_hist(), period="h1", **KW)


def test_unrestricted_is_for_screens_and_not_play_eligible():
    from sportsedge.screen_only_guard import screen_only
    with screen_only():
        p = price_period_unrestricted(_hist(), period="q1", **KW)
    assert "moneyline_3way" in p and p["governance"]["play_allowed"] is False
    assert p["screen_only_unrestricted"] is True
