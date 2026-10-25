"""Synthetic NBA CLV metric regressions; not real DK quotes or graded bets."""
from __future__ import annotations

import pytest

from sportsedge.sports.nba.clv_ledger import clv, clv_summary


def quote(american, opposite):
    return {"american": american, "other_american": opposite}


def test_unchanged_two_sided_quote_has_zero_no_vig_clv():
    result = clv(quote(-110, -110), quote(-110, -110))
    assert result["entry_fair_p"] == pytest.approx(0.5)
    assert result["close_fair_p"] == pytest.approx(0.5)
    assert result["clv_prob"] == pytest.approx(0.0)


def test_vig_only_change_does_not_create_no_vig_clv():
    result = clv(quote(-110, -110), quote(-120, -120))
    assert result["clv_prob"] == pytest.approx(0.0)
    assert result["clv_price_pct"] != pytest.approx(0.0)


@pytest.mark.parametrize("close,sign", [
    (quote(-125, +105), +1),
    (quote(+105, -125), -1),
])
def test_no_vig_clv_sign_reflects_market_move(close, sign):
    result = clv(quote(-110, -110), close)
    assert sign * result["clv_prob"] > 0


def test_opposite_sides_have_equal_opposite_no_vig_clv():
    away = clv(quote(-110, -110), quote(-125, +105))
    home = clv(quote(-110, -110), quote(+105, -125))
    assert away["clv_prob"] == pytest.approx(-home["clv_prob"])


def test_summary_mean_no_vig_clv_zero_for_unchanged_market():
    result = clv(quote(-110, -110), quote(-110, -110))
    summary = clv_summary([{"market": "MONEYLINE", **result}])
    assert summary["MONEYLINE"]["mean_clv_prob"] == pytest.approx(0.0)
    assert summary["MONEYLINE"]["status"] == "EXPERIMENTAL_NO_VERDICT"
