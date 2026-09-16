import pytest
from sportsedge.mlb_moneyline_clv import MLBMoneylineCLVError,evaluate_paired_closes,paired_no_vig

def test_frozen_no_vig_sums_to_one():
    h,a=paired_no_vig(-150,135)
    assert h+a==pytest.approx(1)
    assert h>a

def test_empty_blocked():
    assert evaluate_paired_closes([])["promotion_authority"] is False

def test_clv_uses_frozen_power_policy_and_stays_non_authoritative():
    o=evaluate_paired_closes([
        {"game_pk":1,"model_side":"HOME","model_p":.62,"close_home_odds":-140,"close_away_odds":125},
        {"game_pk":2,"model_side":"AWAY","model_p":.58,"close_home_odds":120,"close_away_odds":-130},
    ])
    assert o["n"]==2
    assert o["devig_policy_id"]=="EDGE_FLOOR_DEVIG_V1"
    assert o["devig_method"]=="POWER_V1"
    assert o["longshot_candidate_estimator"]=="POWER_V1"
    assert o["promotion_authority"] is False

def test_unpaired_rejected():
    with pytest.raises(MLBMoneylineCLVError):
        evaluate_paired_closes([{"game_pk":1,"model_side":"HOME","model_p":.6,"close_home_odds":-120}])

def test_longshot_sensitivity_fails_closed():
    with pytest.raises(MLBMoneylineCLVError,match="LONGSHOT_DEVIG_SENSITIVITY_EXCEEDS_LIMIT"):
        evaluate_paired_closes([{"game_pk":1,"model_side":"AWAY","model_p":.2,"close_home_odds":-700,"close_away_odds":500}])
