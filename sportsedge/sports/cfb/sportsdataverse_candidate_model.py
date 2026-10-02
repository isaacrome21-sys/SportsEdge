"""Native 10-metric SportsDataverse CFB candidate score model.

Selection engineering only. No Model_P, promotion, staking, Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any,Mapping,Sequence
import numpy as np
from .joint_model import _ridge
from .sportsdataverse_candidate_families import (
 FAMILY_EQUAL_WEIGHT_HARD_SWITCH as EQUAL,
 FAMILY_RELIABILITY_WEIGHTED_HARD_SWITCH as RELIABILITY,
 FAMILY_PRIOR_CURRENT_BLEND as BLEND,
 FAMILY_GAMES_IN_SAMPLE_FEATURE as GAMES,
 materialize_candidate_row,
)

TEAM_KEYS=("off_ppa_rush","off_ppa_dropback","def_ppa_rush_allowed","def_ppa_dropback_allowed",
"off_success_rate","def_success_rate_allowed","standard_down_ppa","passing_down_success_rate",
"explosive_rate","net_field_position")
FAMILIES=(EQUAL,RELIABILITY,BLEND,GAMES)
class SDVNativeModelError(ValueError): pass

def _num(v,name):
 try: x=float(v)
 except (TypeError,ValueError) as exc: raise SDVNativeModelError("CFB_SDV_FEATURE_NUMERIC_REQUIRED:"+name) from exc
 if not isfinite(x): raise SDVNativeModelError("CFB_SDV_FEATURE_NONFINITE:"+name)
 return x

def feature_names(family):
 names=[f"home_{k}" for k in TEAM_KEYS]+[f"away_{k}" for k in TEAM_KEYS]
 names+=["home_rush_matchup","home_pass_matchup","away_rush_matchup","away_pass_matchup",
 "home_success_matchup","away_success_matchup","field_position_diff","explosive_diff",
 "home_field","indoors","wind_speed","temperature"]
 if family==GAMES: names+=["home_games_in_sample_feature","away_games_in_sample_feature"]
 return tuple(names)

def feature_vector(family,row,constants=None):
 r=materialize_candidate_row(family,row,constants=constants)
 h=r.get("home_metrics") or {}; a=r.get("away_metrics") or {}
 hv=[_num(h.get(k),"home."+k) for k in TEAM_KEYS]; av=[_num(a.get(k),"away."+k) for k in TEAM_KEYS]
 neutral=r.get("neutral_site",False)
 if type(neutral) is not bool: raise SDVNativeModelError("CFB_SDV_NEUTRAL_SITE_BOOL_REQUIRED")
 weather=r.get("weather")
 if not isinstance(weather,Mapping): raise SDVNativeModelError("CFB_SDV_WEATHER_MAPPING_REQUIRED")
 indoor=weather.get("game_indoor",weather.get("gameIndoors"))
 if type(indoor) is not bool: raise SDVNativeModelError("CFB_SDV_WEATHER_INDOOR_FLAG_REQUIRED")
 if indoor: wind,temp=0.0,70.0
 else:
  wind=_num(weather.get("wind_speed",weather.get("windSpeed")),"weather.wind_speed")
  temp=_num(weather.get("temperature"),"weather.temperature")
 vals=hv+av+[hv[0]-av[2],hv[1]-av[3],av[0]-hv[2],av[1]-hv[3],
 hv[4]-av[5],av[4]-hv[5],hv[9]-av[9],hv[8]-av[8],
 0.0 if neutral else 1.0,1.0 if indoor else 0.0,wind,temp]
 if family==GAMES:
  vals += [_num(r.get("home_games_in_sample_feature"),"home_games_in_sample_feature"),
           _num(r.get("away_games_in_sample_feature"),"away_games_in_sample_feature")]
 return np.asarray(vals,dtype=float)

@dataclass(frozen=True)
class NativeScoreModel:
 family:str; feature_names:tuple[str,...]; means:tuple[float,...]; scales:tuple[float,...]
 home_coef:tuple[float,...]; away_coef:tuple[float,...]; ridge_alpha:float
 def predict_means(self,row,constants=None):
  raw=feature_vector(self.family,row,constants)
  x=np.concatenate(([1.0],(raw-np.asarray(self.means))/np.asarray(self.scales)))
  return float(x@np.asarray(self.home_coef)),float(x@np.asarray(self.away_coef))

def fit_native_score_model(rows:Sequence[Mapping[str,Any]],*,family:str,ridge_alpha:float,constants=None):
 if family not in FAMILIES: raise SDVNativeModelError("CFB_SDV_FAMILY_UNKNOWN")
 if len(rows)<20: raise SDVNativeModelError("CFB_SDV_TRAINING_ROWS_INSUFFICIENT")
 raw=np.asarray([feature_vector(family,r,constants) for r in rows],dtype=float)
 means=raw.mean(axis=0); scales=raw.std(axis=0); scales=np.where(scales>1e-12,scales,1.0)
 x=np.column_stack((np.ones(len(rows)),(raw-means)/scales))
 hy=np.asarray([_num(r.get("home_score"),"home_score") for r in rows]); ay=np.asarray([_num(r.get("away_score"),"away_score") for r in rows])
 return NativeScoreModel(family,feature_names(family),tuple(map(float,means)),tuple(map(float,scales)),
 tuple(map(float,_ridge(x,hy,float(ridge_alpha)))),tuple(map(float,_ridge(x,ay,float(ridge_alpha)))),float(ridge_alpha))
