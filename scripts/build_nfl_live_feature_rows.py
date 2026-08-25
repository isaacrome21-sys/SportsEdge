#!/usr/bin/env python3
"""Build strictly-as-of market-blind NFL M2 rows for upcoming REG games.

The source snapshot is taken before the sportsbook decision snapshot. Only
completed games strictly before ``--asof`` may update football state; target or
in-progress game PBP/participation is excluded. Timestamped depth-chart rows
later than ``--asof`` are also excluded. NFLverse date+gametime values are
interpreted using the same America/New_York contract as historical M2.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.m2_history_features import fit_nfl_prior_decay_curves
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows

_EASTERN = ZoneInfo("America/New_York")
_PBP={"game_id","play_id","posteam","defteam","epa","qb_epa","pass","rush","qb_dropback","passer_player_id","passer_id","yards_gained","play_type"}
_PART={"nflverse_game_id","game_id","play_id","was_pressure"}
_DEPTH={"season","club_code","team","week","game_type","depth_team","position","depth_position","gsis_id","dt","pos_abb","pos_rank"}
_STADIUM={"team_fastr","team","stadium","first_game_date","last_game_date","lat","lon","tz_offset"}
_TEAM_NAMES={
"ARI":"Arizona Cardinals","ATL":"Atlanta Falcons","BAL":"Baltimore Ravens","BUF":"Buffalo Bills","CAR":"Carolina Panthers","CHI":"Chicago Bears","CIN":"Cincinnati Bengals","CLE":"Cleveland Browns","DAL":"Dallas Cowboys","DEN":"Denver Broncos","DET":"Detroit Lions","GB":"Green Bay Packers","HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars","KC":"Kansas City Chiefs","LV":"Las Vegas Raiders","LAC":"Los Angeles Chargers","LA":"Los Angeles Rams","LAR":"Los Angeles Rams","MIA":"Miami Dolphins","MIN":"Minnesota Vikings","NE":"New England Patriots","NO":"New Orleans Saints","NYG":"New York Giants","NYJ":"New York Jets","PHI":"Philadelphia Eagles","PIT":"Pittsburgh Steelers","SEA":"Seattle Seahawks","SF":"San Francisco 49ers","TB":"Tampa Bay Buccaneers","TEN":"Tennessee Titans","WAS":"Washington Commanders","WSH":"Washington Commanders"}


def _dt(v,err):
    raw=str(v or "").strip()
    if not raw: raise SystemExit(err)
    try: d=datetime.fromisoformat(raw[:-1]+"+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc: raise SystemExit(err) from exc
    if d.tzinfo is None or d.utcoffset() is None: raise SystemExit(err)
    return d.astimezone(timezone.utc)


def _start(row):
    explicit=row.get("game_start_ts") or row.get("start_time")
    if explicit not in (None,""):
        return _dt(explicit,"NFL_LIVE_GAME_START_INVALID")
    day=str(row.get("gameday") or row.get("game_date") or "").strip()
    clock=str(row.get("gametime") or "").strip()
    if not day or not clock:
        raise SystemExit(f"NFL_LIVE_GAME_START_MISSING:{row.get('game_id')}")
    try:
        local=datetime.combine(date.fromisoformat(day[:10]),time.fromisoformat(clock),tzinfo=_EASTERN)
    except ValueError as exc:
        raise SystemExit(f"NFL_LIVE_GAME_START_INVALID:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def _open(path): return gzip.open(path,"rt",encoding="utf-8-sig",newline="") if path.suffix==".gz" else path.open("r",encoding="utf-8-sig",newline="")


def _read(path,fields):
    with _open(path) as f:
        r=csv.DictReader(f)
        if r.fieldnames is None: raise SystemExit(f"NFL_LIVE_SOURCE_HEADER_MISSING:{path}")
        chosen=[x for x in r.fieldnames if x in fields]
        if not chosen: raise SystemExit(f"NFL_LIVE_SOURCE_FIELDS_MISSING:{path}")
        return [{x:row.get(x,"") for x in chosen} for row in r]


def _files(root,pattern,start,end):
    out=[]
    for season in range(start,end+1):
        candidates=[root/pattern.format(season=season,ext="csv.gz"),root/pattern.format(season=season,ext="csv")]
        found=[p for p in candidates if p.exists()]
        if len(found)!=1: raise SystemExit(f"NFL_LIVE_SOURCE_FILE_COUNT:{season}:{pattern}:{len(found)}")
        out.append(found[0])
    return out


def _extend(dst,paths,fields):
    for p in paths: dst.extend(_read(p,fields))


def _game_id(row): return str(row.get("game_id") or row.get("nflverse_game_id") or "").strip()


def _completed(row):
    return row.get("home_score") not in (None,"") and row.get("away_score") not in (None,"")


def _depth_asof(rows,asof):
    out=[]
    for row in rows:
        raw=row.get("dt")
        if raw not in (None,""):
            try: stamp=_dt(raw,"NFL_LIVE_DEPTH_TS_INVALID")
            except SystemExit: raise
            if stamp>asof: continue
        out.append(row)
    return out


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--schedule-file",type=Path,required=True); p.add_argument("--pbp-dir",type=Path,required=True); p.add_argument("--participation-dir",type=Path,required=True); p.add_argument("--depth-dir",type=Path,required=True); p.add_argument("--stadium-file",type=Path,required=True)
    p.add_argument("--asof",required=True); p.add_argument("--start-season",type=int,default=2016); p.add_argument("--current-season",type=int,required=True); p.add_argument("--horizon-minutes",type=int,default=120); p.add_argument("--min-lead-minutes",type=int,default=45); p.add_argument("--out",type=Path,default=Path("artifacts/football/nfl_live_features.json")); a=p.parse_args()
    asof=_dt(a.asof,"NFL_LIVE_ASOF_INVALID")
    if a.current_season<a.start_season: raise SystemExit("NFL_LIVE_SEASON_RANGE_INVALID")
    if a.min_lead_minutes<1 or a.horizon_minutes<a.min_lead_minutes: raise SystemExit("NFL_LIVE_WINDOW_INVALID")
    schedule=normalize_nfl_rows(parse_schedule_csv(a.schedule_file.read_text(encoding="utf-8-sig")),range(a.start_season,a.current_season+1))
    starts={str(r.get("game_id") or "").strip():_start(r) for r in schedule if str(r.get("game_id") or "").strip()}
    target={gid for gid,s in starts.items() if asof+timedelta(minutes=a.min_lead_minutes)<=s<=asof+timedelta(minutes=a.horizon_minutes)}
    target={gid for gid in target if next((str(r.get("game_type") or "").upper() for r in schedule if str(r.get("game_id") or "")==gid),"")=="REG"}
    if not target: raise SystemExit("NFL_LIVE_NO_TARGET_GAMES")

    pbpf=_files(a.pbp_dir,"play_by_play_{season}.{ext}",a.start_season,a.current_season); partf=_files(a.participation_dir,"pbp_participation_{season}.{ext}",a.start_season,a.current_season); depthf=_files(a.depth_dir,"depth_charts_{season}.{ext}",a.start_season,a.current_season)
    pbp=[]; part=[]; depth=[]; _extend(pbp,pbpf,_PBP); _extend(part,partf,_PART); _extend(depth,depthf,_DEPTH)
    completed_ids={str(r.get("game_id") or "").strip() for r in schedule if str(r.get("game_id") or "").strip() and starts.get(str(r.get("game_id") or "").strip(),asof)>=datetime.min.replace(tzinfo=timezone.utc) and starts[str(r.get("game_id") or "").strip()]<asof and _completed(r)}
    pbp=[r for r in pbp if _game_id(r) in completed_ids]; part=[r for r in part if _game_id(r) in completed_ids]
    depth=_depth_asof(depth,asof)
    if any(_game_id(r) in target for r in pbp) or any(_game_id(r) in target for r in part): raise SystemExit("NFL_LIVE_TARGET_GAME_LEAK")
    stadiums=_read(a.stadium_file,_STADIUM)
    curves=fit_nfl_prior_decay_curves(schedule,pbp,min_train_seasons=2,weeks=range(1,7))
    rows=build_nfl_m2_history_rows(schedule,pbp,part,depth,stadiums,prior_decay_curves=curves,neutral_site_policy="exclude_from_evaluation")
    live=[]
    for row in rows:
        if str(row.get("game_id") or "") not in target: continue
        item=dict(row); item["home_features"]=dict(item["home_features"]); item["away_features"]=dict(item["away_features"])
        item["home_features"]["feature_asof_ts"]=asof.isoformat(); item["away_features"]["feature_asof_ts"]=asof.isoformat(); item["live_source_asof_ts"]=asof.isoformat()
        home=str(item.get("home_team") or ""); away=str(item.get("away_team") or "")
        if home not in _TEAM_NAMES or away not in _TEAM_NAMES: raise SystemExit(f"NFL_LIVE_PROVIDER_TEAM_MAP_MISSING:{away}:{home}")
        item["provider_home_team"]=_TEAM_NAMES[home]; item["provider_away_team"]=_TEAM_NAMES[away]
        for k in ("spread_line","home_spread_odds","away_spread_odds","total_line","over_odds","under_odds","home_score","away_score"): item.pop(k,None)
        live.append(item)
    if not live: raise SystemExit("NFL_LIVE_FEATURE_ROWS_EMPTY")

    source_paths=[a.schedule_file,a.stadium_file,*pbpf,*partf,*depthf]
    source_rows=[{"path":str(p),"sha256":_sha(p)} for p in source_paths]
    source_hash=hashlib.sha256(json.dumps(source_rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    payload={"schema_version":2,"sport":"nfl","asof_ts":asof.isoformat(),"source_manifest_sha256":source_hash,"source_files":source_rows,"completed_game_count":len(completed_ids),"target_game_count":len(live),"games":live}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"asof_ts":asof.isoformat(),"source_manifest_sha256":source_hash,"completed_game_count":len(completed_ids),"target_game_count":len(live),"game_ids":[r["game_id"] for r in live]},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
