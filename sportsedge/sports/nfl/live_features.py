"""Strictly-as-of market-blind NFL M2 live-feature construction.

This is the reusable implementation behind the production CLI. It consumes
already-frozen local source files and returns the same canonical payload used by
NFL live execution. Network acquisition remains outside this module.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any
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


def _dt(v: Any, err: str) -> datetime:
    raw=str(v or "").strip()
    if not raw: raise ValueError(err)
    try: d=datetime.fromisoformat(raw[:-1]+"+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc: raise ValueError(err) from exc
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError(err)
    return d.astimezone(timezone.utc)


def _start(row: dict[str,Any]) -> datetime:
    explicit=row.get("game_start_ts") or row.get("start_time")
    if explicit not in (None,""): return _dt(explicit,"NFL_LIVE_GAME_START_INVALID")
    day=str(row.get("gameday") or row.get("game_date") or "").strip(); clock=str(row.get("gametime") or "").strip()
    if not day or not clock: raise ValueError(f"NFL_LIVE_GAME_START_MISSING:{row.get('game_id')}")
    try: local=datetime.combine(date.fromisoformat(day[:10]),time.fromisoformat(clock),tzinfo=_EASTERN)
    except ValueError as exc: raise ValueError(f"NFL_LIVE_GAME_START_INVALID:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def _open(path: Path):
    return gzip.open(path,"rt",encoding="utf-8-sig",newline="") if path.suffix==".gz" else path.open("r",encoding="utf-8-sig",newline="")


def _read(path: Path, fields: set[str]) -> list[dict[str,str]]:
    with _open(path) as f:
        r=csv.DictReader(f)
        if r.fieldnames is None: raise ValueError(f"NFL_LIVE_SOURCE_HEADER_MISSING:{path}")
        chosen=[x for x in r.fieldnames if x in fields]
        if not chosen: raise ValueError(f"NFL_LIVE_SOURCE_FIELDS_MISSING:{path}")
        return [{x:row.get(x,"") for x in chosen} for row in r]


def _files(root: Path, pattern: str, start: int, end: int) -> list[Path]:
    out=[]
    for season in range(start,end+1):
        candidates=[root/pattern.format(season=season,ext="csv.gz"),root/pattern.format(season=season,ext="csv")]
        found=[p for p in candidates if p.exists()]
        if len(found)!=1: raise ValueError(f"NFL_LIVE_SOURCE_FILE_COUNT:{season}:{pattern}:{len(found)}")
        out.append(found[0])
    return out


def _extend(dst: list[dict[str,str]], paths: list[Path], fields: set[str]) -> None:
    for p in paths: dst.extend(_read(p,fields))


def _game_id(row: dict[str,Any]) -> str:
    return str(row.get("game_id") or row.get("nflverse_game_id") or "").strip()


def _completed(row: dict[str,Any]) -> bool:
    return row.get("home_score") not in (None,"") and row.get("away_score") not in (None,"")


def _depth_asof(rows: list[dict[str,str]], asof: datetime) -> list[dict[str,str]]:
    out=[]
    for row in rows:
        raw=row.get("dt")
        if raw not in (None,"") and _dt(raw,"NFL_LIVE_DEPTH_TS_INVALID")>asof: continue
        out.append(row)
    return out


def build_nfl_live_feature_payload(
    *,
    schedule_file: Path,
    pbp_dir: Path,
    participation_dir: Path,
    depth_dir: Path,
    stadium_file: Path,
    asof: str | datetime,
    start_season: int = 2016,
    current_season: int,
    horizon_minutes: int = 120,
    min_lead_minutes: int = 45,
) -> dict[str,Any]:
    """Build the canonical live M2 payload from frozen local source files."""
    stamp=_dt(asof,"NFL_LIVE_ASOF_INVALID")
    if current_season<start_season: raise ValueError("NFL_LIVE_SEASON_RANGE_INVALID")
    if min_lead_minutes<1 or horizon_minutes<min_lead_minutes: raise ValueError("NFL_LIVE_WINDOW_INVALID")
    schedule=normalize_nfl_rows(parse_schedule_csv(schedule_file.read_text(encoding="utf-8-sig")),range(start_season,current_season+1))
    starts={str(r.get("game_id") or "").strip():_start(r) for r in schedule if str(r.get("game_id") or "").strip()}
    target={gid for gid,s in starts.items() if stamp+timedelta(minutes=min_lead_minutes)<=s<=stamp+timedelta(minutes=horizon_minutes)}
    target={gid for gid in target if next((str(r.get("game_type") or "").upper() for r in schedule if str(r.get("game_id") or "")==gid),"")=="REG"}
    if not target: raise ValueError("NFL_LIVE_NO_TARGET_GAMES")

    completed_ids={str(r.get("game_id") or "").strip() for r in schedule if str(r.get("game_id") or "").strip() and starts[str(r.get("game_id") or "").strip()]<stamp and _completed(r)}
    replay_ids=completed_ids|target
    replay_schedule=[r for r in schedule if str(r.get("game_id") or "").strip() in replay_ids]
    if not any(str(r.get("game_id") or "").strip() in target for r in replay_schedule): raise ValueError("NFL_LIVE_TARGET_SCHEDULE_MISSING")

    pbpf=_files(pbp_dir,"play_by_play_{season}.{ext}",start_season,current_season)
    partf=_files(participation_dir,"pbp_participation_{season}.{ext}",start_season,current_season)
    depthf=_files(depth_dir,"depth_charts_{season}.{ext}",start_season,current_season)
    pbp=[]; part=[]; depth=[]
    _extend(pbp,pbpf,_PBP); _extend(part,partf,_PART); _extend(depth,depthf,_DEPTH)
    pbp=[r for r in pbp if _game_id(r) in completed_ids]
    part=[r for r in part if _game_id(r) in completed_ids]
    depth=_depth_asof(depth,stamp)
    if any(_game_id(r) in target for r in pbp) or any(_game_id(r) in target for r in part): raise ValueError("NFL_LIVE_TARGET_GAME_LEAK")

    stadiums=_read(stadium_file,_STADIUM)
    curves=fit_nfl_prior_decay_curves(replay_schedule,pbp,min_train_seasons=2,weeks=range(1,7))
    rows=build_nfl_m2_history_rows(replay_schedule,pbp,part,depth,stadiums,prior_decay_curves=curves,neutral_site_policy="exclude_from_evaluation")
    live=[]
    for row in rows:
        if str(row.get("game_id") or "") not in target: continue
        item=dict(row); item["home_features"]=dict(item["home_features"]); item["away_features"]=dict(item["away_features"])
        item["home_features"]["feature_asof_ts"]=stamp.isoformat(); item["away_features"]["feature_asof_ts"]=stamp.isoformat(); item["live_source_asof_ts"]=stamp.isoformat()
        home=str(item.get("home_team") or ""); away=str(item.get("away_team") or "")
        if home not in _TEAM_NAMES or away not in _TEAM_NAMES: raise ValueError(f"NFL_LIVE_PROVIDER_TEAM_MAP_MISSING:{away}:{home}")
        item["provider_home_team"]=_TEAM_NAMES[home]; item["provider_away_team"]=_TEAM_NAMES[away]
        for k in ("spread_line","home_spread_odds","away_spread_odds","total_line","over_odds","under_odds","home_score","away_score"): item.pop(k,None)
        live.append(item)
    if not live: raise ValueError("NFL_LIVE_FEATURE_ROWS_EMPTY")

    source_paths=[schedule_file,stadium_file,*pbpf,*partf,*depthf]
    source_rows=[{"path":str(p),"sha256":_sha(p)} for p in source_paths]
    source_hash=hashlib.sha256(json.dumps(source_rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {
        "schema_version":3,
        "sport":"nfl",
        "asof_ts":stamp.isoformat(),
        "source_manifest_sha256":source_hash,
        "source_files":source_rows,
        "completed_game_count":len(completed_ids),
        "replay_game_count":len(replay_schedule),
        "target_game_count":len(live),
        "games":live,
    }
