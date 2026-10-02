import json
from pathlib import Path
import pytest
from sportsedge.sports.cfb.sportsdataverse_weather import bind_historical_weather,require_complete_weather,SDVWeatherError

def test_outdoor_weather_requires_kickoff_fields():
 with pytest.raises(SDVWeatherError,match="wind_speed"):
  bind_historical_weather({"game_id":1},{"game_indoor":False,"temperature":72})

def test_indoor_weather_can_omit_wind_and_temperature():
 row=bind_historical_weather({"game_id":1},{"game_indoor":True,"wind_speed":None,"temperature":None})
 assert row["weather_status"]=="WEATHER_BOUND"

def test_missing_weather_cannot_enter_bakeoff():
 with pytest.raises(SDVWeatherError,match="HISTORICAL_WEATHER_INCOMPLETE"):
  require_complete_weather([{"game_id":1,"weather_status":"WEATHER_MISSING"}])


def test_frozen_weather_provider_is_public_and_venue_bound():
 contract=json.loads(Path("config/cfb_sportsdataverse_historical_weather_contract_v1.json").read_text())
 assert contract["join_identity"]==["game_id","venue_id","start_date"]
 assert contract["provider"]["source_id"]=="OPEN_METEO_ARCHIVE_V1"
 assert contract["provider"]["selection"]=="NEAREST_KICKOFF_HOUR_NO_INTERPOLATION"
 assert contract["provider"]["missing_hour_policy"]=="FAIL_CLOSED"
 venue=contract["venue_metadata"]
 assert venue["source_commit_sha"]=="aea8274b8c2035372d19d8a509423b0645b7bfe9"
 assert venue["source_content_sha256"]=="aa9599316d015eb10bf019c2fae937c09140061f9940b29dde884030183820f2"
 assert venue["missing_venue_policy"]=="FAIL_CLOSED"
