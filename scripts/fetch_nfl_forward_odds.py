#!/usr/bin/env python3
"""Fetch raw DraftKings NFL game-market snapshots for forward CLV collection.

Credentials come only from SPORTSEDGE_ODDS_API_KEY[_2.._4]. Keys are never
printed. The output is the untouched provider JSON needed by the replayable
forward-capture contract.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import fetch_with_key_failover

_BASE="https://api.the-odds-api.com/v4"
_SPORT="americanfootball_nfl"
_KEYS=("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4")


def _fetch(url_without_key: str, key: str):
    sep="&" if "?" in url_without_key else "?"
    url=f"{url_without_key}{sep}{urlencode({'apiKey':key})}"
    with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":"SportsEdge-NFL-Forward/1"}),timeout=20) as response:
        raw=response.read()
    try: return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise RuntimeError("NFL_FORWARD_ODDS_RESPONSE_JSON_INVALID") from exc


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--event-id"); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
    params={"regions":"us","bookmakers":"draftkings","oddsFormat":"american","dateFormat":"iso"}
    if a.event_id:
        event_id=str(a.event_id).strip()
        if not event_id or "/" in event_id: raise SystemExit("NFL_FORWARD_EVENT_ID_INVALID")
        params["markets"]="h2h,spreads,totals,alternate_spreads,alternate_totals"
        base=f"{_BASE}/sports/{_SPORT}/events/{event_id}/odds?{urlencode(params)}"
    else:
        params["markets"]="h2h,spreads,totals"
        base=f"{_BASE}/sports/{_SPORT}/odds?{urlencode(params)}"
    keys=[os.environ.get(name,"") for name in _KEYS]
    result=fetch_with_key_failover(keys,lambda key:_fetch(base,key))
    payload=result.value
    if a.event_id and not isinstance(payload,dict): raise SystemExit("NFL_FORWARD_EVENT_ODDS_NOT_OBJECT")
    if not a.event_id and not isinstance(payload,list): raise SystemExit("NFL_FORWARD_SPORT_ODDS_NOT_LIST")
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"mode":"event" if a.event_id else "sport","key_slot":result.key_slot,"prior_key_failures":len(result.failures),"row_count":1 if isinstance(payload,dict) else len(payload)},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
