"""CFB Lane B retirement: no synthetic zero-weight market probabilities."""
import pytest
from tests.test_contract_repairs_20261011 import model, NOW, row

RETIRED = "CFB_LANE_B_RETIRED_NO_OOS_WIN"


@pytest.mark.parametrize("market,side,line,odds,opposite", [
    ("TOTAL", "OVER", 47.5, -110, -110),
    ("TOTAL", "UNDER", 48, +105, -125),  # integer push
    ("SPREAD", "HOME", -3.5, -115, -105),
    ("SPREAD", "AWAY", +3, +102, -125),  # integer push
    ("ML", "HOME", 0, +150, -175),  # asymmetric vig, plus money
    ("ML", "AWAY", 0, -160, +130),
    ("ML", "HOME", 0, -110, None),  # unpaired quote cannot revive Lane B
])
def test_cfb_retired_lane_cannot_emit_price_or_ev(
    market, side, line, odds, opposite,
):
    r = row(sport="CFB", away="Away", home="Home", market=market,
            side=side, line=line, odds=odds, opposite_odds=opposite)
    independent = model.calculate(
        r, model.PublicContext(NOW), NOW, auto_context=False, lane="A")
    retired = independent["pricing_lanes"]["lane_b_anchored"]
    assert independent["pricing_lane"] == "LANE_A_INDEPENDENT"
    assert independent["pricing_lanes"]["lane_a_independent"]["estimate_p"] == pytest.approx(
        independent["estimate_p"])
    assert retired["lane"] == "LANE_B_ANCHORED"
    assert retired["status"] == "LANE_B_UNAVAILABLE"
    assert retired["reason"] == RETIRED
    assert retired["anchor"]["status"] == "RETIRED_NO_OUT_OF_SAMPLE_WIN"
    assert retired["anchor"]["weight"] == 0.0
    for key in ("estimate_p", "ev_per_dollar", "fair_american",
                "push_p", "fair_total", "fair_home_margin", "market_no_vig_p"):
        assert key not in retired
        assert key not in retired["anchor"]
    assert not retired["validated_vs_close"]
    blocked = model.calculate(
        r, model.PublicContext(NOW), NOW, auto_context=False, lane="B")
    assert blocked["status"] == RETIRED
    assert blocked["research_only"] is True
    assert "estimate_p" not in blocked and "ev_per_dollar" not in blocked


@pytest.mark.parametrize("market,side,line", [
    ("TOTAL", "OVER", 47.5),
    ("SPREAD", "HOME", -3.5),
    ("ML", "HOME", 0),
])
def test_non_cfb_lane_b_unchanged(market, side, line):
    r = row(sport="NFL", away="Away", home="Home", market=market,
            side=side, line=line, opposite_odds=-115)
    result = model.calculate(r, model.PublicContext(NOW), NOW,
                             auto_context=False, lane="B")
    anchor = result["pricing_lanes"]["lane_b_anchored"]["anchor"]
    assert anchor["weight"] == pytest.approx(0.15)
    assert "estimate_p" in result["pricing_lanes"]["lane_b_anchored"]


def test_cfb_retired_lane_absent_from_card_ranking():
    r = row(sport="CFB", away="Away", home="Home",
            market="TOTAL", side="OVER", line=40.5, odds=+120)
    card = model.run({"lines": [r]}, now=NOW, auto_context=False, lane="B")
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []
    assert all(x.get("status") == RETIRED for x in card["evaluated_rows"])
