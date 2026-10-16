"""Independent audit RED (t211 @ 2714013a): authority/EV keys nested in
evaluation.pricing_provenance slip past exact/pattern key screens. Expected to FAIL until fixed."""
import pytest
from sportsedge import composite_card as cc


@pytest.mark.parametrize("prov", [
    {"playEligible": True}, {"is_official": True}, {"approved": True},
    {"actionable": True}, {"ok_to_bet": True}, {"stake_units": 2},
    {"bet_size": 1}, {"units_risked": 1}, {"evPerDollar": 0.12},
])
def test_nested_provenance_authority_or_money_key_refused(prov):
    assert cc.authority_violation({"evaluation": {"pricing_provenance": prov}}) is not None


@pytest.mark.parametrize("v", ["\uff30\uff2c\uff21\uff39", "p.l.a.y"])
def test_obfuscated_promotion_value_refused(v):
    assert cc.authority_violation({"evaluation": {"reason": v}}) is not None
