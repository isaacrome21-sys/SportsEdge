"""Owner-directed CFB-only removal of unsupported residual weight."""
import pytest
from tests.test_contract_repairs_20261011 import model, NOW, row

@pytest.mark.parametrize("market,side,line", [("TOTAL", "OVER", 47.5), ("SPREAD", "HOME", -3.5), ("ML", "HOME", 0)])
def test_cfb_residual_zero_other_sports_unchanged(market, side, line):
    for sport, expected in [("CFB", 0.0), ("NFL", 0.15)]:
        r = row(sport=sport, away="Away", home="Home", market=market,
                side=side, line=line, opposite_odds=-115)
        result = model.calculate(r, model.PublicContext(NOW), NOW, auto_context=False)
        anchor = result["pricing_lanes"]["lane_b_anchored"]["anchor"]
        assert anchor["weight"] == expected
        if sport == "CFB":
            if market == "TOTAL":
                assert anchor["fair_total"] == line
            elif market == "SPREAD":
                assert anchor["fair_home_margin"] == -line
            else:
                assert result["pricing_lanes"]["lane_b_anchored"]["estimate_p"] == pytest.approx(anchor["market_no_vig_p"], abs=1e-6)
