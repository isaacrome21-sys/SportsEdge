import json

import scripts.acquire_cfb_sportsdataverse_training_inputs as acquire


def test_acquisition_source_contains_no_api_secret_or_sportsbook_dependency():
    source=open(
        "scripts/acquire_cfb_sportsdataverse_training_inputs.py",
        encoding="utf-8",
    ).read()
    workflow=open(
        ".github/workflows/cfb-sdv-materialize-training.yml",
        encoding="utf-8",
    ).read()
    for token in (
        "CFBD_API_KEY",
        "SPORTSEDGE_CFBD_API_KEY",
        "SPORTSEDGE_ODDS_API_KEY",
        "ODDS_API_KEY",
        "the-odds-api",
    ):
        assert token.lower() not in source.lower()
        assert token.lower() not in workflow.lower()
    assert "OPEN_METEO_ARCHIVE_V1" in open(
        "config/cfb_sportsdataverse_historical_weather_contract_v1.json",
        encoding="utf-8",
    ).read()


def test_window_job_is_open_meteo_and_receipted(monkeypatch):
    seen={}
    payload={"hourly":{
        "time":["2025-09-06T19:00","2025-09-06T20:00"],
        "temperature_2m":[71,70],
        "wind_speed_10m":[7,8],
    }}
    raw=json.dumps(payload).encode()

    def fake_get(url,*,headers=None,attempts=4):
        seen["url"]=url
        seen["headers"]=dict(headers or {})
        return raw

    monkeypatch.setattr(acquire,"_get",fake_get)
    rows,receipt=acquire._window_job(
        season=2025,
        venue={
            "stadium_id":"test-stadium",
            "venue_id":123,
            "latitude":40.0,
            "longitude":-88.0,
            "game_indoor":False,
        },
        games=[{
            "game_id":11,
            "season":2025,
            "venue_id":123,
            "start_date":"2025-09-06T19:20:00Z",
        }],
    )
    assert "archive-api.open-meteo.com" in seen["url"]
    assert "Authorization" not in seen["headers"]
    assert rows[0]["game_id"]==11
    assert receipt["season"]==2025
    assert receipt["stadium_id"]=="test-stadium"
    assert receipt["cfbd_venue_id"]==123
    assert receipt["source_id"]=="OPEN_METEO_ARCHIVE_V1"
