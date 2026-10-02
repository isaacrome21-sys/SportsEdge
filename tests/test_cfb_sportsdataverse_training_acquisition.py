import json

import scripts.acquire_cfb_sportsdataverse_training_inputs as acquire


def test_weather_acquisition_is_season_scoped_cfbd_and_receipted(monkeypatch):
    seen={}
    payload=[
        {"id":11,"gameIndoors":False,"windSpeed":7,"temperature":71},
        {"id":12,"gameIndoors":True,"windSpeed":None,"temperature":None},
    ]
    raw=json.dumps(payload).encode("utf-8")

    def fake_get(url,*,headers=None,attempts=3):
        seen["url"]=url
        seen["headers"]=dict(headers or {})
        return raw

    monkeypatch.setattr(acquire,"_get",fake_get)
    season,rows,receipt=acquire._weather_for_season(
        season=2025,
        game_ids=[11,12],
        api_key="secret",
    )
    assert season==2025
    assert "year=2025" in seen["url"]
    assert "seasonType=regular" in seen["url"]
    assert "classification=fbs" in seen["url"]
    assert seen["headers"]["Authorization"]=="Bearer secret"
    assert [r["game_id"] for r in rows]==[11,12]
    assert receipt["season"]==2025
    assert receipt["source_id"]=="CFBD_GAMES_WEATHER_V1"
    assert receipt["row_count"]==2


def test_acquisition_source_contains_no_sportsbook_dependency():
    source=open(
        "scripts/acquire_cfb_sportsdataverse_training_inputs.py",
        encoding="utf-8",
    ).read()
    assert "SPORTSEDGE_ODDS_API_KEY" not in source
    assert "ODDS_API_KEY" not in source
    assert "the-odds-api" not in source.lower()
