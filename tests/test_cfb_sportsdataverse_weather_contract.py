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


def test_frozen_weather_provider_is_game_id_scoped_cfbd():
 contract=json.loads(Path("config/cfb_sportsdataverse_historical_weather_contract_v1.json").read_text())
 assert contract["join_identity"]==["game_id"]
 assert contract["provider"]["source_id"]=="CFBD_GAMES_WEATHER_V1"
 assert contract["provider"]["interpolation"] is False
 assert contract["provider"]["missing_game_policy"]=="FAIL_CLOSED"
