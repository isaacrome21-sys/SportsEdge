import pytest
from sportsedge.sports.cfb.sportsdataverse_weather_transport import *


def test_request_is_frozen_regular_fbs_season():
    p=request_params(season=2025)
    assert p=={"year":2025,"seasonType":"regular","classification":"fbs"}
    with pytest.raises(SDVWeatherTransportError,match="OUTSIDE_FROZEN_WINDOW"):
        request_params(season=2026)


def test_normalize_outdoor_and_indoor_weather():
    rows=normalize_season_weather(
        [
            {"id":1,"gameIndoors":False,"temperature":70,"windSpeed":8},
            {"id":2,"gameIndoors":True,"temperature":65,"windSpeed":4},
            {"id":999,"gameIndoors":False,"temperature":80,"windSpeed":3},
        ],
        season=2025,
        evaluated_game_ids=[1,2],
    )
    assert rows==[
        {"game_id":1,"game_indoor":False,"wind_speed":8.0,"temperature":70.0},
        {"game_id":2,"game_indoor":True,"wind_speed":None,"temperature":None},
    ]


def test_missing_evaluated_game_fails_closed():
    with pytest.raises(SDVWeatherTransportError,match="HISTORICAL_WEATHER_INCOMPLETE"):
        normalize_season_weather(
            [{"id":1,"gameIndoors":False,"temperature":70,"windSpeed":8}],
            season=2025,
            evaluated_game_ids=[1,2],
        )


def test_outdoor_weather_requires_numeric_fields():
    with pytest.raises(SDVWeatherTransportError,match="windSpeed"):
        normalize_season_weather(
            [{"id":1,"gameIndoors":False,"temperature":70,"windSpeed":None}],
            season=2025,
            evaluated_game_ids=[1],
        )


def test_indoor_flag_and_duplicates_fail_closed():
    with pytest.raises(SDVWeatherTransportError,match="INDOOR_FLAG_REQUIRED"):
        normalize_season_weather(
            [{"id":1,"gameIndoors":None}],
            season=2025,
            evaluated_game_ids=[1],
        )
    with pytest.raises(SDVWeatherTransportError,match="DUPLICATE_GAME"):
        normalize_season_weather(
            [
                {"id":1,"gameIndoors":True},
                {"id":1,"gameIndoors":True},
            ],
            season=2025,
            evaluated_game_ids=[1],
        )
