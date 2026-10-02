import numpy as np
from sportsedge.sports.cfb.sportsdataverse_candidate_model import FAMILIES,feature_names,feature_vector

KEYS=("off_ppa_rush","off_ppa_dropback","def_ppa_rush_allowed","def_ppa_dropback_allowed",
"off_success_rate","def_success_rate_allowed","standard_down_ppa","passing_down_success_rate","explosive_rate","net_field_position")
def metrics(base,games=2):
 return {**{k:base+i/100 for i,k in enumerate(KEYS)},"games_in_sample":games,"season":2025,"through_week":2,"sample_source":"CURRENT_SEASON_PRIOR_WEEKS"}
def prior(base):
 return {**{k:base+i/100 for i,k in enumerate(KEYS)},"games_in_sample":12,"season":2024,"through_week":14,"sample_source":"PRIOR_SEASON_FALLBACK"}
def row():
 return {"season":2025,"week":3,"neutral_site":False,"weather":{"game_indoor":False,"wind_speed":8,"temperature":70},
 "home_metrics":metrics(.1),"away_metrics":metrics(.2),
 "home_prior_metrics":prior(.05),"away_prior_metrics":prior(.15),
 "home_current_metrics":metrics(.1),"away_current_metrics":metrics(.2)}

def test_all_four_native_families_have_finite_vectors_without_legacy_metrics():
 r=row()
 for family in FAMILIES:
  constants={}
  if "RELIABILITY" in family: constants={"min_current_games":3}
  elif family=="PRIOR_CURRENT_BLEND": constants={"prior_equivalent_games":4}
  elif family=="GAMES_IN_SAMPLE_FEATURE": constants={"games_in_sample_cap":12,"normalization_divisor":12}
  v=feature_vector(family,r,constants)
  assert np.all(np.isfinite(v))
  assert len(v)==len(feature_names(family))
  assert not any(x in feature_names(family) for x in ("home_eckel_rate","home_points_per_eckel","home_points_per_drive"))
