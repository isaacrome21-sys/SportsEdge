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


def test_batch_request_and_response_mapping_are_request_order_deterministic():
 locations=[
  {"venue_id":10,"latitude":40.0,"longitude":-88.0},
  {"venue_id":20,"latitude":41.0,"longitude":-89.0},
 ]
 p=batch_request_params(locations=locations,start_date="2025-09-01",end_date="2025-12-01",max_locations=50)
 assert p["latitude"]=="40.0,41.0" and p["longitude"]=="-88.0,-89.0"
 payload=[
  {"hourly":{"time":[],"temperature_2m":[],"wind_speed_10m":[]}},
  {"hourly":{"time":[],"temperature_2m":[],"wind_speed_10m":[]}},
 ]
 mapped=map_batch_payload(payload,locations=locations)
 assert list(mapped)==[10,20]
 assert mapped[10] is payload[0] and mapped[20] is payload[1]


def test_batch_size_fails_closed():
 with pytest.raises(SDVWeatherTransportError,match="BATCH_TOO_LARGE"):
  batch_request_params(
   locations=[{"venue_id":1,"latitude":40.0,"longitude":-88.0},{"venue_id":2,"latitude":41.0,"longitude":-89.0}],
   start_date="2025-09-01",end_date="2025-09-02",max_locations=1,
  )
