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


def batch_request_params(*, locations:Sequence[Mapping[str,Any]],start_date:str,end_date:str,max_locations:int=50)->dict[str,Any]:
 if not locations: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_LOCATIONS_REQUIRED")
 if len(locations)>int(max_locations): raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_TOO_LARGE")
 try:
  start=datetime.fromisoformat(str(start_date)).date(); end=datetime.fromisoformat(str(end_date)).date()
 except Exception as e: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_DATE_INVALID") from e
 if end<start: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_DATE_ORDER_INVALID")
 lats=[]; lons=[]
 for row in locations:
  try: lat=float(row["latitude"]); lon=float(row["longitude"])
  except (KeyError,TypeError,ValueError) as e: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_COORDINATE_INVALID") from e
  if not (-90<=lat<=90 and -180<=lon<=180): raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_COORDINATE_RANGE_INVALID")
  lats.append(str(lat)); lons.append(str(lon))
 return {"latitude":",".join(lats),"longitude":",".join(lons),"start_date":start.isoformat(),"end_date":end.isoformat(),
         "hourly":",".join(HOURLY),"temperature_unit":"fahrenheit","wind_speed_unit":"mph","timezone":"UTC"}

def map_batch_payload(payload:Any,*,locations:Sequence[Mapping[str,Any]])->dict[int,Mapping[str,Any]]:
 if len(locations)==1 and isinstance(payload,Mapping): rows=[payload]
 elif isinstance(payload,list): rows=payload
 else: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_PAYLOAD_INVALID")
 if len(rows)!=len(locations): raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_RESPONSE_LENGTH_MISMATCH")
 out={}
 for location,row in zip(locations,rows):
  if not isinstance(row,Mapping): raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_RESPONSE_ROW_INVALID")
  try: venue_id=int(location["venue_id"])
  except (KeyError,TypeError,ValueError) as e: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_VENUE_ID_INVALID") from e
  if venue_id in out: raise SDVWeatherTransportError("CFB_SDV_WEATHER_BATCH_VENUE_DUPLICATE")
  out[venue_id]=row
 return out

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
