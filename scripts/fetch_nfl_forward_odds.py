#!/usr/bin/env python3
"""Fetch raw DraftKings NFL game-market snapshots for forward CLV collection.

Credentials come only from SPORTSEDGE_ODDS_API_KEY[_2.._4]. Keys are never
printed. Acquisition is delegated to the reusable NFL odds source so workflow
and AUTOMATIC execution share one provider contract.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sportsedge.sports.nfl.odds_source import fetch_nfl_odds

_KEYS=("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4")


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--event-id"); p.add_argument("--out",type=Path,required=True); a=p.parse_args()
    keys=[os.environ.get(name,"") for name in _KEYS]
    try:
        result=fetch_nfl_odds(keys,event_id=a.event_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload=result.value
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"mode":"event" if a.event_id else "sport","key_slot":result.key_slot,"prior_key_failures":len(result.failures),"row_count":1 if isinstance(payload,dict) else len(payload)},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
