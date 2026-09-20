import pytest
from sportsedge.sports.nfl.attd_features import build_attd_feature_rows,attd_research_score

def _r(w,td=0,xtd=.2):
 return {"player_id":"p","season":2026,"week":w,"rushing_tds":td,"receiving_tds":0,"expected_tds":xtd,"snap_share":.8,"route_share":.5,"target_share":.2,"rush_share":.6,"goal_line_expected_tds":.1,"red_zone_expected_tds":.1}

def test_attd_features_are_shifted_and_label_current_game_only():
 rows=[_r(1),_r(2,1),_r(3),_r(4,1,9.0)]
 x=build_attd_feature_rows(rows,min_prior_games=3)[0]
 assert x["week"]==4 and x["expected_tds_l5"]==pytest.approx(.2)
 assert x["label_any_td"]==1

def test_td_debt_is_descriptive_prior_only():
 rows=[_r(1,1,.2),_r(2,0,.3),_r(3,0,.4),_r(4)]
 x=build_attd_feature_rows(rows,min_prior_games=3)[0]
 assert x["td_debt_l5"]==pytest.approx(-.1)

def test_research_score_is_not_probability_and_bounded():
 x={"snap_share_l5":1,"rush_share_l5":1,"target_share_l5":1,"route_share_l5":1,"expected_tds_l5":2,"goal_line_xtd_l5":2,"red_zone_xtd_l5":2}
 assert attd_research_score(x)==100.0
