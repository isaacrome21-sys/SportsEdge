import pytest
from sportsedge.sports.cfb.sportsdataverse_weather_transport import *

def test_request_is_utc_and_fixed_units():
 p=request_params(latitude=40.0,longitude=-88.0,kickoff_utc="2025-09-06T19:20:00-05:00")
 assert p["start_date"]=="2025-09-07" and p["timezone"]=="UTC"
 assert p["temperature_unit"]=="fahrenheit" and p["wind_speed_unit"]=="mph"

def test_select_nearest_hour_without_interpolation():
 payload={"hourly":{"time":["2025-09-07T00:00","2025-09-07T01:00"],"temperature_2m":[70,69],"wind_speed_10m":[8,9]}}
 r=select_kickoff_hour(payload,game_id=1,kickoff_utc="2025-09-07T00:20:00Z",game_indoor=False)
 assert r["temperature"]==70 and r["wind_speed"]==8

def test_indoor_does_not_require_weather_payload():
 assert select_kickoff_hour({},game_id=1,kickoff_utc="2025-09-07T00:20:00Z",game_indoor=True)["temperature"] is None

def test_missing_hour_fails_closed():
 with pytest.raises(SDVWeatherTransportError,match="KICKOFF_HOUR_MISSING"):
  select_kickoff_hour({"hourly":{"time":[],"temperature_2m":[],"wind_speed_10m":[]}},game_id=1,kickoff_utc="2025-09-07T00:20:00Z",game_indoor=False)
