import pytest
from sportsedge.sports.cfb.sportsdataverse_bakeoff import SDVNativeBakeoffError,evaluate_native_candidates
from sportsedge.sports.cfb.sportsdataverse_candidate_model import TEAM_KEYS

def m(v,g=5,season=2020,through=4,source="CURRENT_SEASON_PRIOR_WEEKS"):
 return {**{k:v+i*.01 for i,k in enumerate(TEAM_KEYS)},"games_in_sample":g,"season":season,"through_week":through,"sample_source":source}
def rows():
 out=[]
 for season in range(2015,2021):
  for i in range(20):
   week=5
   hp=m(.1+i*.001,season=season); ap=m(.2+i*.001,season=season)
   priorh=m(.08,12,season-1,14,"PRIOR_SEASON_FALLBACK"); priora=m(.18,12,season-1,14,"PRIOR_SEASON_FALLBACK")
   out.append({"game_id":f"{season}-{i}","season":season,"week":week,"home_id":1,"away_id":2,
    "neutral_site":False,"weather":{"game_indoor":True},"weather_status":"WEATHER_BOUND","home_metrics":hp,"away_metrics":ap,
    "home_prior_metrics":priorh,"away_prior_metrics":priora,"home_current_metrics":hp,"away_current_metrics":ap,
    "home_score":24+(i%3),"away_score":20+(i%2)})
 return out
CFG={"candidate_selection_policy":{"metric":"JOINT_HOME_AWAY_SCORE_RMSE","tie_break":"LOWEST_RMSE_THEN_FROZEN_FAMILY_ORDER","family_order":["EQUAL_WEIGHT_HARD_SWITCH","RELIABILITY_WEIGHTED_HARD_SWITCH","PRIOR_CURRENT_BLEND","GAMES_IN_SAMPLE_FEATURE"],"post_result_override_allowed":False},"candidates":{"EQUAL_WEIGHT_HARD_SWITCH":{"constants":{}},"RELIABILITY_WEIGHTED_HARD_SWITCH":{"constants":{"min_current_games":3}},
 "PRIOR_CURRENT_BLEND":{"constants":{"prior_equivalent_games":4}},"GAMES_IN_SAMPLE_FEATURE":{"constants":{"games_in_sample_cap":12,"normalization_divisor":12}}},
 "hyperparameter_policy":{"ridge_alpha_grid":[0.1,1,3]}}

def test_native_bakeoff_is_expanding_season_and_all_four_families():
 r=evaluate_native_candidates(rows(),CFG)
 assert r["outer_validation_seasons"]==[2018,2019,2020]
 assert set(r["observed"])==set(CFG["candidates"])
 assert r["selected_family"] in CFG["candidates"]
 assert r["selection_tie_break"]=="LOWEST_RMSE_THEN_FROZEN_FAMILY_ORDER"
 assert all(v["folds"][0]["season"]==2018 for v in r["observed"].values())
 assert r["authority"]["model_p_created"] is False

def test_2026_outcome_fails_closed():
 data=rows(); data[0]["season"]=2026
 with pytest.raises(SDVNativeBakeoffError,match="2026_OUTCOMES"):
  evaluate_native_candidates(data,CFG)

def test_missing_weather_blocks_evaluation():
 data=rows(); data[0]["weather_status"]="WEATHER_MISSING"; data[0]["weather"]=None
 with pytest.raises(Exception,match="HISTORICAL_WEATHER_INCOMPLETE"):
  evaluate_native_candidates(data,CFG)
