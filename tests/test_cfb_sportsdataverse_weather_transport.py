import hashlib
import json

import pytest
from sportsedge.sports.cfb.sportsdataverse_weather_transport import *


def _venue_csv():
    return (
        "stadium_id,name,aliases,city,state,country,lat,lon,elevation_m,timezone,"
        "orientation_deg,orientation_bucket,orientation_src,roof_type,surface,"
        "capacity,year_built,avg_wind_static,wind_vol_static,wind_impact_static,"
        "weakest_wind_effect,avg_wind_sep,avg_wind_oct,avg_wind_nov,avg_wind_dec,"
        "avg_wind_jan,avg_temp_f,wikidata_qid,osm_way_id,cfbd_venue_id,espn_venue_id,"
        "nflverse_stadium_id,needs_review,elev_src,latlon_src,review_note\n"
        "x,Test Stadium,,,,US,40.0,-88.0,,,,,,open,,,,,,,,,,,,,,,,123,,,,,,\n"
        "y,Dome,,,,US,41.0,-87.0,,,,,,dome,,,,,,,,,,,,,,,,124,,,,,,\n"
    ).encode()


def test_venue_index_requires_pinned_hash(monkeypatch):
    raw=_venue_csv()
    monkeypatch.setattr(
        "sportsedge.sports.cfb.sportsdataverse_weather_transport.VENUE_SOURCE_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    idx=venue_index(raw)
    assert idx[123]["game_indoor"] is False
    assert idx[124]["game_indoor"] is True
    with pytest.raises(SDVWeatherTransportError,match="HASH_MISMATCH"):
        venue_index(raw+b"x")


def test_request_is_fixed_open_meteo_contract():
    p=request_params(
        latitude=40.0,
        longitude=-88.0,
        start_date="2025-09-06",
        end_date="2025-09-07",
    )
    assert p["timezone"]=="UTC"
    assert p["temperature_unit"]=="fahrenheit"
    assert p["wind_speed_unit"]=="mph"
    assert p["hourly"]=="temperature_2m,wind_speed_10m"


def test_select_nearest_hour_without_interpolation():
    payload={"hourly":{
        "time":["2025-09-07T00:00","2025-09-07T01:00"],
        "temperature_2m":[70,69],
        "wind_speed_10m":[8,9],
    }}
    r=select_kickoff_hour(
        payload,
        game_id=1,
        kickoff_utc="2025-09-07T00:20:00Z",
        game_indoor=False,
    )
    assert r["temperature"]==70 and r["wind_speed"]==8


def test_indoor_requires_no_weather_payload():
    r=select_kickoff_hour(
        {},
        game_id=1,
        kickoff_utc="2025-09-07T00:20:00Z",
        game_indoor=True,
    )
    assert r=={
        "game_id":1,
        "game_indoor":True,
        "wind_speed":None,
        "temperature":None,
    }


def test_missing_hour_fails_closed():
    with pytest.raises(SDVWeatherTransportError,match="KICKOFF_HOUR_MISSING"):
        select_kickoff_hour(
            {"hourly":{"time":[],"temperature_2m":[],"wind_speed_10m":[]}},
            game_id=1,
            kickoff_utc="2025-09-07T00:20:00Z",
            game_indoor=False,
        )


def test_exact_name_fallback_resolves_when_cfbd_id_is_not_bound(monkeypatch):
    raw=_venue_csv()
    monkeypatch.setattr(
        "sportsedge.sports.cfb.sportsdataverse_weather_transport.VENUE_SOURCE_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    by_id,by_name=venue_indexes(raw)
    venue,resolution=resolve_venue(
        by_id=by_id,
        by_name=by_name,
        venue_id=999999,
        venue_name="  Test   Stadium ",
    )
    assert venue["stadium_id"]=="x"
    assert resolution=="PINNED_EXACT_NAME_OR_ALIAS"

    venue,resolution=resolve_venue(
        by_id=by_id,
        by_name=by_name,
        venue_id=None,
        venue_name="Test Stadium",
    )
    assert venue["stadium_id"]=="x"
    assert resolution=="PINNED_EXACT_NAME_OR_ALIAS"
