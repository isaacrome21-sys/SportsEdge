#!/usr/bin/env python3
"""Acquire frozen CFB SportsDataverse training inputs without evaluating candidates."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from sportsedge.sports.cfb.sportsdataverse_acquisition import acquisition_plan
from sportsedge.sports.cfb.sportsdataverse_csv import parse_csv
from sportsedge.sports.cfb.sportsdataverse_history import regular_fbs_schedule_rows
from sportsedge.sports.cfb.sportsdataverse_receipts import receipt,validate_receipts
from sportsedge.sports.cfb.sportsdataverse_weather_receipts import bind_weather_rows
from sportsedge.sports.cfb.sportsdataverse_weather_transport import (
    BASE_URL as WEATHER_URL,
    SOURCE_ID as WEATHER_SOURCE_ID,
    normalize_season_weather,
    request_params,
)

UA="SportsEdge-CFB-SDV/1"
FROZEN_FIRST_ROW_SEASON=2016
FROZEN_END_SEASON=2025


def _get(url:str,*,headers:dict[str,str]|None=None,attempts:int=3)->bytes:
    last=None
    for attempt in range(attempts):
        try:
            req=Request(url,headers={"User-Agent":UA,**(headers or {})})
            with urlopen(req,timeout=120) as response:
                return response.read()
        except Exception as exc:
            last=exc
            if attempt+1<attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"CFB_SDV_HTTP_FAILED:{url}") from last


def _strict_true(value)->bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true","1","t"}


def _download_asset(item,root:Path):
    raw=_get(item.url)
    root.mkdir(parents=True,exist_ok=True)
    path=root/item.filename
    path.write_bytes(raw)
    rr=receipt(item,raw)
    rows,pr=parse_csv(
        raw,
        dataset=item.dataset,
        season=item.season,
        source_url=item.url,
        raw_csv_sha256=rr.sha256,
    )
    return item,rr,pr,rows


def _weather_for_season(*,season:int,game_ids:list[int],api_key:str):
    params=request_params(season=season)
    raw=_get(
        WEATHER_URL+"?"+urlencode(params),
        headers={"Authorization":f"Bearer {api_key}","Accept":"application/json"},
    )
    try:
        payload=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise RuntimeError(f"CFB_SDV_WEATHER_JSON_INVALID:{season}") from exc
    if not isinstance(payload,list):
        raise RuntimeError(f"CFB_SDV_WEATHER_JSON_LIST_REQUIRED:{season}")
    rows=normalize_season_weather(
        payload,
        season=season,
        evaluated_game_ids=game_ids,
    )
    bound=bind_weather_rows(raw,rows,source_id=WEATHER_SOURCE_ID)
    return season,rows,{
        "season":season,
        **bound.to_dict(),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--asset-root",type=Path,required=True)
    ap.add_argument("--weather-out",type=Path,required=True)
    ap.add_argument("--weather-receipts-out",type=Path,required=True)
    ap.add_argument("--asset-workers",type=int,default=8)
    ap.add_argument("--weather-workers",type=int,default=4)
    args=ap.parse_args()

    api_key=str(
        os.environ.get("SPORTSEDGE_CFBD_API_KEY")
        or os.environ.get("CFBD_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")

    plan=acquisition_plan()
    with ThreadPoolExecutor(max_workers=max(1,int(args.asset_workers))) as pool:
        acquired=list(pool.map(lambda item:_download_asset(item,args.asset_root),plan))
    acquired.sort(key=lambda x:(x[0].season,x[0].dataset))
    validate_receipts(plan,[x[1] for x in acquired])

    schedules=[]
    for item,_,_,rows in acquired:
        if item.dataset=="cfb_schedules":
            schedules.extend(rows)
    scoped=regular_fbs_schedule_rows(schedules)
    game_ids_by_season={}
    for row in scoped:
        season=int(row["season"])
        if not FROZEN_FIRST_ROW_SEASON<=season<=FROZEN_END_SEASON:
            continue
        if not _strict_true(row.get("completed")):
            continue
        game_ids_by_season.setdefault(season,[]).append(int(row["game_id"]))

    expected=set(range(FROZEN_FIRST_ROW_SEASON,FROZEN_END_SEASON+1))
    if set(game_ids_by_season)!=expected or any(not v for v in game_ids_by_season.values()):
        raise SystemExit("CFB_SDV_EVALUATED_GAME_SEASON_COVERAGE_INVALID")

    with ThreadPoolExecutor(max_workers=max(1,int(args.weather_workers))) as pool:
        futures=[
            pool.submit(
                _weather_for_season,
                season=season,
                game_ids=sorted(set(game_ids_by_season[season])),
                api_key=api_key,
            )
            for season in sorted(game_ids_by_season)
        ]
        weather_parts=[f.result() for f in futures]
    weather_parts.sort(key=lambda x:x[0])
    weather=[row for _,rows,_ in weather_parts for row in rows]
    receipts=[receipt_row for _,_,receipt_row in weather_parts]

    args.weather_out.parent.mkdir(parents=True,exist_ok=True)
    args.weather_recepts_parent = args.weather_receipts_out.parent
    args.weather_recepts_parent.mkdir(parents=True,exist_ok=True)
    args.weather_out.write_text(
        json.dumps(weather,indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    args.weather_receipts_out.write_text(
        json.dumps({
            "schema":"CFB_SDV_HISTORICAL_WEATHER_RECEIPTS_V1",
            "source_id":WEATHER_SOURCE_ID,
            "seasons":receipts,
            "normalized_row_count":len(weather),
            "normalized_rows_sha256":sha256(
                json.dumps(weather,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest(),
            "governance":{
                "attempts_consumed":0,
                "evaluation_performed":False,
                "model_p_created":False,
                "promotion_authority":False,
                "official_authority":False,
            },
        },indent=2,sort_keys=True)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status":"ACQUIRED_NO_EVALUATION",
        "asset_count":len(acquired),
        "weather_row_count":len(weather),
        "weather_seasons":sorted(game_ids_by_season),
        "attempts_consumed":0,
        "evaluation_performed":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
