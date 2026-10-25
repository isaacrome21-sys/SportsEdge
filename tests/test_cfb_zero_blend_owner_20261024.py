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
