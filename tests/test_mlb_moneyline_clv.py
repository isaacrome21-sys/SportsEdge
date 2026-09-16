import pytest
from sportsedge.mlb_moneyline_clv import MLBMoneylineCLVError,evaluate_paired_closes,paired_no_vig
def test_no_vig():
 h,a=paired_no_vig(-150,135);assert h+a==pytest.approx(1) and h>a
def test_empty_blocked():assert evaluate_paired_closes([])["promotion_authority"] is False
def test_separate_non_authoritative():
 o=evaluate_paired_closes([{"game_pk":1,"model_side":"HOME","model_p":.62,"close_home_odds":-140,"close_away_odds":125},{"game_pk":2,"model_side":"AWAY","model_p":.58,"close_home_odds":120,"close_away_odds":-130}]);assert o["n"]==2 and o["devig_method"]=="MULTIPLICATIVE_V1" and o["promotion_authority"] is False
def test_unpaired_rejected():
 with pytest.raises(MLBMoneylineCLVError):evaluate_paired_closes([{"game_pk":1,"model_side":"HOME","model_p":.6,"close_home_odds":-120}])
