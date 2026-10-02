import pytest
from sportsedge.sports.cfb.sportsdataverse_weather_receipts import *

def test_weather_receipt_binds_raw_bytes_and_rows():
 rows=[{"game_id":2,"game_indoor":True,"wind_speed":None,"temperature":None},{"game_id":1,"game_indoor":False,"wind_speed":8,"temperature":71}]
 r=bind_weather_rows(b"weather-source",rows,source_id="historical-weather-v1")
 assert r.row_count==2
 verify_weather_rows(r,b"weather-source",list(reversed(rows)))

def test_weather_receipt_rejects_duplicate_games():
 with pytest.raises(SDVWeatherReceiptError,match="DUPLICATE_GAME"):
  bind_weather_rows(b"x",[{"game_id":1,"game_indoor":True},{"game_id":1,"game_indoor":True}],source_id="x")

def test_weather_receipt_rejects_incomplete_outdoor_weather():
 with pytest.raises(SDVWeatherReceiptError,match="OUTDOOR_FIELDS_REQUIRED"):
  bind_weather_rows(b"x",[{"game_id":1,"game_indoor":False,"wind_speed":None,"temperature":70}],source_id="x")
