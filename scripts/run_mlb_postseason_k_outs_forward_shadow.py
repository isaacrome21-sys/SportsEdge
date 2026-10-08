#!/usr/bin/env python3
"""Capture 2026 postseason pitcher K/outs research predictions before first pitch.

Only today (New York time) may create predictions. Today and yesterday may
settle EXISTING stored predictions. Missing pregame observations stay MISSED;
never reconstitute a past model prediction from later-arriving data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo
import sys

from sportsedge.mlb_generic_features import MLBGenericHistorySource, _read_json
from sportsedge.mlb_source import parse_schedule, fetch_boxscore, parse_game_start
from sportsedge.mlb_postseason_k_outs_forward_shadow import (
    MARKET_LINES, build_prediction, settle_prediction,
)

NEW_YORK=ZoneInfo("America/New_York")
GAME_TYPES=frozenset({"F","D","L","W"})
EVIDENCE_ROOT=Path("data/mlb_postseason_k_outs_forward_2026")


def canonical_hash(payload: Any) -> str:
    return sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def create_only(path:Path,payload:Mapping[str,Any]) -> str:
    raw=json.dumps(dict(payload),indent=2,sort_keys=True,allow_nan=False)+"\n"
    if path.exists():
        if path.read_text(encoding="utf8")!=raw:
            raise ValueError(f"CREATE_ONLY_COLLISION:{path}")
        return "EXISTING_IDENTICAL"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(raw,encoding="utf8")
    return "CREATED"


def games_for_day(day:str, captured:datetime):
    query=urlencode({"sportId":1,"date":day,"hydrate":"probablePitcher,team",
                     "gameTypes":",".join(sorted(GAME_TYPES))})
    url=f"https://statsapi.mlb.com/api/v1/schedule?{query}"
    response=_read_json(url,opener=urlopen)
    if not isinstance(response.get("dates"),list):
        raise ValueError("POSTSEASON_SCHEDULE_MISSING_DATES")
    filtered=[]
    for d in response["dates"]:
        games=[g for g in (d.get("games") or []) if g.get("gameType") in GAME_TYPES]
        if games: filtered.append({**d,"games":games})
    scheduled=parse_schedule({"dates":filtered},captured)
    return scheduled,canonical_hash(response)


def file_prefix(game_pk:int,pitcher_id:int,market:str,line:float)->str:
    return f"{game_pk}_{pitcher_id}_{market}_{str(line).replace('.','p')}.json"


def _existing(path:Path) -> dict[str,Any]:
    record=json.loads(path.read_text(encoding="utf8"))
    if not isinstance(record,dict):raise ValueError("EXISTING_RECEIPT_NOT_OBJECT")
    return record


def run(*, output_root:Path=EVIDENCE_ROOT, now:datetime|None=None)->dict[str,Any]:
    began=now or datetime.now(timezone.utc)
    if began.tzinfo is None or began.utcoffset() is None:raise ValueError("UTC_CLOCK_REQUIRED")
    began=began.astimezone(timezone.utc)
    if began.year!=2026:
        return {"status":"OUTSIDE_2026_RESEARCH_SEASON","created":0}
    current=began.astimezone(NEW_YORK).date()
    summary={"status":"OK","run_at_utc":began.isoformat(),"research_only":True,
             "predictions_created":0,"settlements_created":0,"voids":0,
             "missed":0,"existing":0,"issues":[]}
    source=MLBGenericHistorySource(retrieved_at=began)
    # Yesterday is settlement-only. Never create predictions for historical dates.
    for day in (current-timedelta(days=1),current):
        games,schedule_sha=games_for_day(day.isoformat(),began)
        for game in games:
            if game.status=="Preview" and day==current:
                if not (began<parse_game_start(game.game_date)):
                    summary["issues"].append({"game_pk":game.game_pk,"reason":"PREGAME_WINDOW_EXPIRED"})
                    continue
                target=day
                for side,pid,tid in (("away",game.away_probable_pitcher_id,game.away_id),
                                      ("home",game.home_probable_pitcher_id,game.home_id)):
                    if pid is None:
                        summary["issues"].append({"game_pk":game.game_pk,"team_side":side,
                                                  "reason":"PROBABLE_STARTER_UNKNOWN"})
                        continue
                    for market,lines in MARKET_LINES.items():
                        future=[line for line in lines if not
                            (output_root/"predictions"/file_prefix(game.game_pk,int(pid),market,line)).exists()]
                        if not future:
                            summary["existing"]+=len(lines)
                            continue
                        try:
                            feature=source.feature_row(game_pk=game.game_pk,
                                market=market,entity_id=str(pid),target_date=target,
                                away_team_id=game.away_id,home_team_id=game.home_id,
                                player_id=int(pid),team_id=int(tid))
                            # Fresh wall-clock check after any slow source request.
                            observed=datetime.now(timezone.utc) if now is None else began
                            for line in future:
                                receipt=build_prediction(game=game,pitcher_id=int(pid),
                                    team_side=side,market=market,line=line,feature=feature,
                                    captured_at=observed,schedule_sha256=schedule_sha)
                                destination=output_root/"predictions"/file_prefix(game.game_pk,int(pid),market,line)
                                created=create_only(destination,receipt)
                                summary["predictions_created"]+=int(created=="CREATED")
                        except Exception as exc:
                            summary["issues"].append({"game_pk":game.game_pk,"pitcher_id":int(pid),
                                "market":market,"reason":type(exc).__name__+":"+str(exc)[:160]})
            elif game.status=="Final":
                files=sorted((output_root/"predictions").glob(f"{game.game_pk}_*.json"))
                if not files:
                    path=output_root/"missed"/f"{game.game_pk}.json"
                    receipt={"status":"MISSED_NO_EARLIER_PREGAME_MODEL_RECEIPT",
                             "research_only":True,"game_pk":game.game_pk,
                             "observed_at_utc":began.isoformat()}
                    if create_only(path,receipt)=="CREATED":summary["missed"]+=1
                    continue
                try:
                    box=fetch_boxscore(game.game_pk)
                    boxsha=canonical_hash(box)
                    observed=datetime.now(timezone.utc) if now is None else began
                    for file in files:
                        previous=_existing(file)
                        out=output_root/"settlements"/file.name
                        if out.exists():
                            summary["existing"]+=1
                            continue
                        settlement=settle_prediction(game=game,prediction=previous,
                            boxscore=box,settled_at=observed,
                            final_source_sha256=boxsha)
                        if create_only(out,settlement)=="CREATED":
                            summary["settlements_created"]+=1
                            summary["voids"]+=int(settlement["status"]=="VOID_NOT_ACTUAL_STARTER")
                except Exception as exc:
                    summary["issues"].append({"game_pk":game.game_pk,
                        "reason":"SETTLEMENT_BLOCKED:"+type(exc).__name__+":"+str(exc)[:160]})
            elif game.status=="Live":
                # No late snapshot: in-play data cannot stand in for pregame model evidence.
                if not list((output_root/"predictions").glob(f"{game.game_pk}_*.json")):
                    summary["issues"].append({"game_pk":game.game_pk,"reason":"LIVE_WITHOUT_PREGAME_RECEIPT"})
    if summary["issues"]:
        # Informational misses/unknown starters are visible, not fabricated evidence.
        summary["status"]="PARTIAL_OR_BLOCKED_RESEARCH_EVIDENCE"
    return summary


def main()->int:
    from argparse import ArgumentParser
    p=ArgumentParser()
    p.add_argument("--output-root",type=Path,default=EVIDENCE_ROOT)
    args=p.parse_args()
    try:
        result=run(output_root=args.output_root)
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","reason":str(exc)},sort_keys=True))
        return 2
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result["status"] in ("OK","OUTSIDE_2026_RESEARCH_SEASON") else 2


if __name__=="__main__":
    sys.exit(main())
