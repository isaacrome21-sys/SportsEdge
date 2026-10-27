"""Owner-directed CFB retirement of unsupported market-anchored Lane B."""
import pytest
from tests.test_contract_repairs_20261011 import model, NOW, row

@pytest.mark.parametrize("market,side,line", [("TOTAL", "OVER", 47.5), ("SPREAD", "HOME", -3.5), ("ML", "HOME", 0)])
def test_cfb_residual_zero_other_sports_unchanged(market, side, line):
    for sport, expected in [("CFB", 0.0), ("NFL", 0.15)]:
        r = row(sport=sport, away="Away", home="Home", market=market,
                side=side, line=line, opposite_odds=-115)
        result = model.calculate(r, model.PublicContext(NOW), NOW, auto_context=False)
        lane_b = result["pricing_lanes"]["lane_b_anchored"]
        anchor = lane_b["anchor"]
        assert anchor["weight"] == expected
        if sport == "CFB":
            assert lane_b["status"] == "LANE_B_UNAVAILABLE"
            assert lane_b["reason"] == "CFB_LANE_B_RETIRED_UNVALIDATED"
            assert "estimate_p" not in lane_b
            assert "fair_total" not in anchor
            assert "fair_home_margin" not in anchor
            assert "market_no_vig_p" not in anchor
            blocked = model.calculate(r, model.PublicContext(NOW), NOW,
                                      auto_context=False, lane="B")
            assert blocked["status"] == "CFB_LANE_B_RETIRED_UNVALIDATED"
            assert blocked["research_only"] is True
        else:
            assert lane_b["lane"] == model.LANE_B
            assert lane_b["estimate_p"] >= 0


# Fold in the direct market/quote and card regressions from redundant #2687,
# while preserving this branch's stricter all-CFB-market retirement reason.
@pytest.mark.parametrize("market,side,line,odds,opposite", [
    ("TOTAL", "OVER", 47.5, -110, -110),
    ("TOTAL", "UNDER", 48, +105, -125),  # integer push
    ("SPREAD", "HOME", -3.5, -115, -105),
    ("SPREAD", "AWAY", +3, +102, -125),  # integer push
    ("ML", "HOME", 0, +150, -175),  # asymmetric vig, plus money
    ("ML", "AWAY", 0, -160, +130),
    ("ML", "HOME", 0, -110, None),  # unpaired quote
])
def test_cfb_lane_b_never_emits_market_ev(market, side, line, odds, opposite):
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
    assert retired["reason"] == "CFB_LANE_B_RETIRED_UNVALIDATED"
    assert retired["anchor"]["weight"] == 0.0
    for key in ("estimate_p", "ev_per_dollar", "fair_american",
                "push_p", "fair_total", "fair_home_margin", "market_no_vig_p"):
        assert key not in retired
        assert key not in retired["anchor"]
    assert retired["validated_vs_close"] is False
    blocked = model.calculate(
        r, model.PublicContext(NOW), NOW, auto_context=False, lane="B")
    assert blocked["status"] == "CFB_LANE_B_RETIRED_UNVALIDATED"
    assert blocked["research_only"] is True
    assert "estimate_p" not in blocked and "ev_per_dollar" not in blocked


def test_cfb_retired_lane_absent_from_card_ranking():
    r = row(sport="CFB", away="Away", home="Home",
            market="TOTAL", side="OVER", line=40.5, odds=+120)
    card = model.run({"lines": [r]}, now=NOW, auto_context=False, lane="B")
    assert card["edges"] == []
    assert card["independent_candidates"] == []
    assert card["lane_b_edges"] == []
    assert all(x.get("status") == "CFB_LANE_B_RETIRED_UNVALIDATED"
               for x in card["evaluated_rows"])
