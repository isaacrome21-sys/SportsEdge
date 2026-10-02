"""Frozen historical weather transport for the CFB SportsDataverse lane.

Transport is intentionally narrow: callers provide a venue coordinate and UTC kickoff.
The returned hourly observation is selected deterministically and is never interpolated.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from typing import Any,Mapping,Sequence

class SDVWeatherTransportError(ValueError): pass

SOURCE_ID="OPEN_METEO_ARCHIVE_V1"
BASE_URL="https://archive-api.open-meteo.com/v1/archive"
HOURLY=("temperature_2m","wind_speed_10m")

def request_params(*,latitude:float,longitude:float,kickoff_utc:str)->dict[str,Any]:
 dt=_utc(kickoff_utc)
 day=dt.date()
 return {"latitude":float(latitude),"longitude":float(longitude),"start_date":day.isoformat(),"end_date":(day+timedelta(days=1)).isoformat(),
         "hourly":",".join(HOURLY),"temperature_unit":"fahrenheit","wind_speed_unit":"mph","timezone":"UTC"}

def select_kickoff_hour(payload:Mapping[str,Any],*,game_id:int,kickoff_utc:str,game_indoor:bool)->dict[str,Any]:
 if type(game_indoor) is not bool: raise SDVWeatherTransportError("CFB_SDV_WEATHER_INDOOR_FLAG_REQUIRED")
 if game_indoor:
  return {"game_id":int(game_id),"game_indoor":True,"wind_speed":None,"temperature":None}
 hourly=payload.get("hourly")
 if not isinstance(hourly,Mapping): raise SDVWeatherTransportError("CFB_SDV_WEATHER_HOURLY_REQUIRED")
 times=list(hourly.get("time") or []); temps=list(hourly.get("temperature_2m") or []); winds=list(hourly.get("wind_speed_10m") or [])
 if not (len(times)==len(temps)==len(winds)): raise SDVWeatherTransportError("CFB_SDV_WEATHER_HOURLY_LENGTH_MISMATCH")
 target=_utc(kickoff_utc)
 if target.minute>=30: target=target.replace(minute=0,second=0,microsecond=0)+timedelta(hours=1)
 else: target=target.replace(minute=0,second=0,microsecond=0)
 # Open-Meteo UTC hourly strings omit offset.
 key=target.strftime("%Y-%m-%dT%H:%M")
 if key not in times: raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_HOUR_MISSING")
 i=times.index(key)
 if temps[i] is None or winds[i] is None: raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_VALUES_MISSING")
 return {"game_id":int(game_id),"game_indoor":False,"wind_speed":float(winds[i]),"temperature":float(temps[i])}

def _utc(value:str)->datetime:
 try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
 except Exception as e: raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_INVALID") from e
 if dt.tzinfo is None: raise SDVWeatherTransportError("CFB_SDV_WEATHER_KICKOFF_TZ_REQUIRED")
 return dt.astimezone(timezone.utc)
