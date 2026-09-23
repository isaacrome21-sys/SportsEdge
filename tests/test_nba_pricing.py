import math
import pytest
from sportsedge.sports.nba.pricing import path_outcome, moneyline_probability, expected_value, decimal_to_american


def test_path_price_handles_pushes_without_hiding_them():
    p=path_outcome((10,11,12,13),11,over=True)
    assert p.win_probability == .5
    assert p.push_probability == .25
    assert p.lose_probability == .25
    assert p.fair_decimal == 1.5


def test_moneyline_uses_paired_final_paths():
    p=moneyline_probability((101,110,99),(100,105,102),home=True)
    assert p.win_probability == pytest.approx(2/3)
    assert p.push_probability == 0


def test_ev_uses_win_loss_and_push_return():
    p=path_outcome((12,11,10,13),11,over=True)
    assert expected_value(p,2.0) == pytest.approx(.25)


def test_fair_price_and_quote_validation_fail_closed():
    assert math.isinf(path_outcome((1,1),2,over=True).fair_decimal)
    with pytest.raises(ValueError): path_outcome((),2)
    with pytest.raises(ValueError): expected_value(path_outcome((3,),2),1.0)
    assert decimal_to_american(2.5) == 150
    assert decimal_to_american(1.5) == -200
