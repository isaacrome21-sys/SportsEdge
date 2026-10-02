"""Historical weather binding guard for the SportsDataverse CFB candidate lane."""
from __future__ import annotations
from typing import Any,Mapping,Sequence

class SDVWeatherError(ValueError): pass
REQUIRED=("game_indoor","wind_speed","temperature")

def bind_historical_weather(row:Mapping[str,Any],weather:Mapping[str,Any]|None)->dict[str,Any]:
 out=dict(row)
 if weather is None:
  out["weather"]=None
  out["weather_status"]="WEATHER_MISSING"
  return out
 w=dict(weather)
 if type(w.get("game_indoor")) is not bool:
  raise SDVWeatherError("CFB_SDV_WEATHER_INDOOR_FLAG_REQUIRED")
 if not w["game_indoor"]:
  for key in ("wind_speed","temperature"):
   if w.get(key) is None: raise SDVWeatherError("CFB_SDV_WEATHER_FIELD_REQUIRED:"+key)
 out["weather"]=w
 out["weather_status"]="WEATHER_BOUND"
 return out

def require_complete_weather(rows:Sequence[Mapping[str,Any]])->None:
 missing=[str(r.get("game_id","UNKNOWN")) for r in rows if r.get("weather_status")!="WEATHER_BOUND"]
 if missing:
  raise SDVWeatherError("CFB_SDV_HISTORICAL_WEATHER_INCOMPLETE:"+",".join(missing[:20]))
