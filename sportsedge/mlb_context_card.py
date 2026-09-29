"""Card section for MLB pregame context that a SportsEdge run actually retrieved."""
from __future__ import annotations
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping
LANES=(("starters","Starters"),("lineups","Lineups"),("umpire","Umpire"),("weather_roof","Weather/roof"),("park_venue","Park/venue"),("statcast","Statcast"),("bullpen_workload","Bullpen workload"),("injuries_scratches","Injuries/scratches"))
_HIGHLIGHTS={"umpire":("umpire_name","sample_gate","home_plate_games"),"weather_roof":("roof_state","temperature","wind_speed","wind_direction","precip_probability_pct","short_forecast"),"park_venue":("venue_name","roof_type","turf_type"),"statcast":("bound_pitcher_count","bound_hitter_count","window_start","window_end"),"bullpen_workload":("bullpen_pitches_24h","bullpen_pitches_48h","bullpen_pitches_72h","back_to_back_reliever_ids","high_usage_48h_reliever_ids")}
def lane_sha256(lane:Any)->str:
 return sha256(json.dumps(lane,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _find(obj,key):
 if isinstance(obj,Mapping):
  if key in obj and not isinstance(obj[key],(Mapping,list)): return obj[key]
  if key in obj and isinstance(obj[key],Mapping) and "value" in obj[key]: return obj[key]["value"]
  for v in obj.values():
   x=_find(v,key)
   if x is not None:return x
 elif isinstance(obj,list):
  for v in obj:
   x=_find(v,key)
   if x is not None:return x
 return None
def _starters(lane):
 p=lane.get("probable_pitchers") or {}; n=[]
 for s in ("away","home"):
  q=p.get(s) if isinstance(p,Mapping) else None;n.append((q or {}).get("player_name") or (q or {}).get("player_id") or "TBD")
 return f"{n[0]} vs {n[1]}"
def _bullpen(lane):
 teams=lane.get("teams") or {}; parts=[]
 for side in ("away","home"):
  row=teams.get(side) if isinstance(teams,Mapping) else None
  if not isinstance(row,Mapping):
   parts.append(f"{side}=missing");continue
  parts.append(f"{side}:24h {row.get('bullpen_pitches_24h','—')}p, 48h {row.get('bullpen_pitches_48h','—')}p, B2B {len(row.get('back_to_back_reliever_ids') or [])}")
 return " | ".join(parts)
def lane_line(key,label,bundle):
 lane=bundle.get(key)
 if not isinstance(lane,Mapping):return f"- {label}: NOT RETRIEVED this run"
 parts=[f"{label}: {lane.get('status','UNKNOWN')}"]
 if key=="starters":parts.append(_starters(lane))
 elif key=="lineups":
  c=lane.get("complete_by_side") or {};parts.append(f"official 9 posted — away {bool(c.get('away'))}, home {bool(c.get('home'))}")
 elif key=="bullpen_workload":parts.append(_bullpen(lane))
 for field in _HIGHLIGHTS.get(key,()):
  v=_find(lane,field)
  if v not in (None,"",[]):parts.append(f"{field}={v}")
 parts.append(f"source {lane.get('source') or bundle.get('source')}, as of {lane.get('as_of_utc') or lane.get('retrieved_at') or bundle.get('as_of_utc')}, sha {lane_sha256(lane)[:12]}")
 e=lane.get("errors") or ([lane["error"]] if lane.get("error") else [])
 if e:parts.append("errors: "+"; ".join(str(x) for x in list(e)[:3]))
 return "- "+" · ".join(str(x) for x in parts)
def context_section(bundles:Iterable[Mapping[str,Any]],*,failures:Iterable[str]=()):
 lines=["","## Context retrieved this run (NOT used by model_p)","_Pulled live by this SportsEdge run from StatsAPI / Baseball Savant / NWS. Every lane is `model_p_eligible = false`: the engine probabilities above did not use it._"]
 failures=list(failures); any_bundle=False
 for b in bundles:
  any_bundle=True;lines+=["",f"**Game {b.get('game_pk')}** · bundle {str(b.get('payload_sha256',''))[:12]} · retrieved {b.get('as_of_utc')} · readiness {b.get('status')}"]
  for k,l in LANES:lines.append(lane_line(k,l,b))
 for f in failures:lines.append(f"- {f}")
 if not any_bundle and not failures:lines.append("- No context bundles were retrieved this run.")
 return lines
