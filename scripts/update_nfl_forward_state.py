#!/usr/bin/env python3
"""Offline durable state machine for scheduled NFL forward CLV collection.

Network acquisition belongs to the workflow. This script only consumes frozen
schedule/features/provider snapshots and mutates a release-scoped state folder.
It is deliberately safe across scheduled runs: decisions are immutable, closes
can only be added once, and only SHADOW_QUALIFIED/OFFICIAL observations are
eligible for the promotable complete-pair export.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sportsedge.core.clv.nfl_forward_capture import build_forward_close_rows
from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.live_runner import run_canonical_nfl_live
from sportsedge.sports.nfl.model_artifact import load_nfl_m2_model_artifact

_EASTERN = ZoneInfo("America/New_York")
_PROMOTION_GATES = {"SHADOW_QUALIFIED", "OFFICIAL"}


def _dt(value: Any, error: str) -> datetime:
    raw=str(value or "").strip()
    if not raw: raise SystemExit(error)
    try: out=datetime.fromisoformat(raw[:-1]+"+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc: raise SystemExit(error) from exc
    if out.tzinfo is None or out.utcoffset() is None: raise SystemExit(error)
    return out.astimezone(timezone.utc)


def _start(row: Mapping[str,Any]) -> datetime:
    explicit=row.get("game_start_ts") or row.get("start_time")
    if explicit not in (None,""): return _dt(explicit,"NFL_FORWARD_PLAN_GAME_START_INVALID")
    day=str(row.get("gameday") or row.get("game_date") or "").strip(); clock=str(row.get("gametime") or "").strip()
    if not day or not clock: raise SystemExit(f"NFL_FORWARD_PLAN_GAME_START_MISSING:{row.get('game_id')}")
    try: local=datetime.combine(date.fromisoformat(day[:10]),time.fromisoformat(clock),tzinfo=_EASTERN)
    except ValueError as exc: raise SystemExit(f"NFL_FORWARD_PLAN_GAME_START_INVALID:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise SystemExit(f"NFL_FORWARD_STATE_JSON_INVALID:{path}") from exc


def _jsonl(path: Path) -> list[dict[str,Any]]:
    if not path.exists(): return []
    rows=[]
    for i,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: row=json.loads(line)
        except json.JSONDecodeError as exc: raise SystemExit(f"NFL_FORWARD_STATE_JSONL_INVALID:{path}:{i}") from exc
        if not isinstance(row,dict): raise SystemExit(f"NFL_FORWARD_STATE_ROW_INVALID:{path}:{i}")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Iterable[Mapping[str,Any]]) -> None:
    material=[dict(x) for x in rows]
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in material),encoding="utf-8")
    tmp.replace(path)


def _key(row: Mapping[str,Any]) -> tuple[str,str,str,str]:
    key=(str(row.get("game_id") or "").strip(),str(row.get("market") or "").strip().lower(),str(row.get("side") or "").strip(),str(row.get("book") or "").strip().lower())
    if not all(key): raise SystemExit("NFL_FORWARD_STATE_PAIR_IDENTITY_MISSING")
    return key


def _assert_unique(rows: Iterable[Mapping[str,Any]], label: str) -> None:
    seen=set()
    for row in rows:
        key=_key(row)
        if key in seen: raise SystemExit(f"NFL_FORWARD_STATE_DUPLICATE_{label}:{key}")
        seen.add(key)


def _state_paths(root: Path) -> tuple[Path,Path,Path]:
    return root/"decisions.jsonl",root/"closes.jsonl",root/"release.json"


def _release(model_path: Path) -> tuple[dict[str,Any],str,str]:
    payload=_json(model_path)
    if not isinstance(payload,dict): raise SystemExit("NFL_FORWARD_MODEL_ARTIFACT_NOT_OBJECT")
    model_sha=str(payload.get("code_git_sha") or "").strip().lower()
    model_hash=_sha(model_path)
    load_nfl_m2_model_artifact(payload,expected_code_git_sha=model_sha)
    return payload,model_sha,model_hash


def _bind_release(state_dir: Path, model_sha: str, model_hash: str) -> None:
    _,_,release_path=_state_paths(state_dir)
    expected={"schema_version":1,"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash}
    if release_path.exists():
        current=_json(release_path)
        if current!=expected: raise SystemExit("NFL_FORWARD_STATE_MODEL_RELEASE_MISMATCH")
    else:
        release_path.parent.mkdir(parents=True,exist_ok=True)
        release_path.write_text(json.dumps(expected,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def _schedule(path: Path) -> list[dict[str,Any]]:
    raw=parse_schedule_csv(path.read_text(encoding="utf-8-sig"))
    seasons=sorted({int(float(x["season"])) for x in raw if x.get("season") not in (None,"")})
    return normalize_nfl_rows(raw,seasons)


def _forward_schedule_scope(schedule: list[dict[str,Any]], now: datetime, *, decision_max: int) -> tuple[int,list[dict[str,Any]]]:
    regular=[row for row in schedule if str(row.get("game_type") or "").upper()=="REG"]
    seasons=[]
    for row in regular:
        try:
            season=int(row.get("season") or 0)
        except (TypeError,ValueError):
            continue
        if 0 < season <= now.year:
            seasons.append(season)
    if not seasons:
        return 0,[]
    current=max(seasons)
    horizon_days=max(1,int(decision_max//1440)+1)
    floor=now.date()-timedelta(days=1)
    ceiling=now.date()+timedelta(days=horizon_days)
    scoped=[]
    for row in regular:
        try:
            season=int(row.get("season") or 0)
        except (TypeError,ValueError):
            continue
        if season!=current:
            continue
        explicit=str(row.get("game_start_ts") or row.get("start_time") or "").strip()
        day=str(row.get("gameday") or row.get("game_date") or "").strip()
        coarse=(explicit or day)[:10]
        if coarse:
            try:
                game_day=date.fromisoformat(coarse)
            except ValueError:
                # A current-season row with invalid date identity is not safe to
                # silently discard; allow _start() to fail closed below.
                scoped.append(row)
                continue
            if game_day < floor or game_day > ceiling:
                continue
        else:
            # Current-season rows with no date cannot be proven out of scope.
            # They must reach _start() and fail closed rather than disappear.
            scoped.append(row)
            continue
        scoped.append(row)
    return current,scoped


def plan(schedule_file: Path, state_dir: Path, now: datetime, *, decision_min: int, decision_max: int, close_min: int, close_max: int) -> dict[str,Any]:
    decisions_path,closes_path,_=_state_paths(state_dir)
    decisions=_jsonl(decisions_path); closes=_jsonl(closes_path); _assert_unique(decisions,"DECISION"); _assert_unique(closes,"CLOSE")
    decided_games={str(x.get("game_id") or "") for x in decisions}
    closed={_key(x) for x in closes}
    schedule=_schedule(schedule_file)
    current_season,forward_rows=_forward_schedule_scope(schedule,now,decision_max=decision_max)
    due=[]
    for row in forward_rows:
        gid=str(row.get("game_id") or "").strip()
        if not gid or gid in decided_games: continue
        lead=(_start(row)-now).total_seconds()/60.0
        if decision_min<=lead<=decision_max: due.append(gid)
    close_ids=set(); expired=0; pending=0
    by_event={}
    for row in decisions:
        if str(row.get("gate_result") or "") not in _PROMOTION_GATES: continue
        if _key(row) in closed: continue
        pending+=1
        start=_dt(row.get("game_start_ts"),"NFL_FORWARD_STATE_GAME_START_INVALID")
        lead=(start-now).total_seconds()/60.0
        event_id=str(row.get("provider_event_id") or "").strip()
        if not event_id: raise SystemExit("NFL_FORWARD_STATE_PROVIDER_EVENT_ID_MISSING")
        by_event.setdefault(event_id,[]).append(row)
        if lead<=0: expired+=1
        elif close_min<=lead<=close_max: close_ids.add(event_id)
    return {"schema_version":1,"now":now.isoformat(),"current_season":current_season,"decision_due":bool(due),"decision_game_ids":sorted(due),"close_event_ids":sorted(close_ids),"pending_qualifying_rows":pending,"expired_unclosed_rows":expired,"decision_row_count":len(decisions),"close_row_count":len(closes)}


def _events(payload: Any) -> list[dict[str,Any]]:
    if not isinstance(payload,list): raise SystemExit("NFL_FORWARD_ODDS_EVENTS_NOT_LIST")
    rows=[dict(x) for x in payload if isinstance(x,Mapping)]
    if len(rows)!=len(payload): raise SystemExit("NFL_FORWARD_ODDS_EVENT_MALFORMED")
    return rows


def _canonical_live_error(exc: ValueError) -> SystemExit:
    message=str(exc)
    aliases={
        "NFL_LIVE_FEATURE_PAYLOAD_INVALID":"NFL_FORWARD_LIVE_FEATURE_PAYLOAD_INVALID",
        "NFL_LIVE_FEATURE_SOURCE_HASH_INVALID":"NFL_FORWARD_LIVE_FEATURE_SOURCE_HASH_INVALID",
        "NFL_LIVE_FEATURE_ASOF_INVALID":"NFL_FORWARD_LIVE_FEATURE_ASOF_INVALID",
        "NFL_LIVE_FEATURE_FROM_FUTURE":"NFL_FORWARD_LIVE_FEATURE_FROM_FUTURE",
        "NFL_LIVE_FEATURE_GAMES_EMPTY":"NFL_FORWARD_LIVE_FEATURE_GAMES_EMPTY",
        "NFL_LIVE_FEATURE_GAME_INVALID":"NFL_FORWARD_LIVE_FEATURE_GAME_INVALID",
        "NFL_LIVE_FEATURE_GAME_ID_MISSING":"NFL_FORWARD_LIVE_FEATURE_GAME_ID_MISSING",
        "NFL_LIVE_PROVIDER_TEAM_IDENTITY_MISSING":"NFL_FORWARD_PROVIDER_TEAM_IDENTITY_MISSING",
        "NFL_LIVE_GAME_START_INVALID":"NFL_FORWARD_GAME_START_INVALID",
        "NFL_LIVE_PROVIDER_EVENT_NOT_FOUND":"NFL_FORWARD_PROVIDER_EVENT_NOT_FOUND",
        "NFL_LIVE_PROVIDER_EVENT_AMBIGUOUS":"NFL_FORWARD_PROVIDER_EVENT_AMBIGUOUS",
        "NFL_LIVE_DECISION_MARKET_COUNT_INVALID":"NFL_FORWARD_DECISION_MARKET_COUNT_INVALID",
    }
    return SystemExit(aliases.get(message,message))


def decision_mode(state_dir: Path, model_path: Path, features_path: Path, odds_path: Path, captured: datetime) -> dict[str,Any]:
    decisions_path,closes_path,_=_state_paths(state_dir)
    decisions=_jsonl(decisions_path); closes=_jsonl(closes_path); _assert_unique(decisions,"DECISION"); _assert_unique(closes,"CLOSE")
    artifact,model_sha,model_hash=_release(model_path); _bind_release(state_dir,model_sha,model_hash)
    model=load_nfl_m2_model_artifact(artifact,expected_code_git_sha=model_sha)
    features=_json(features_path)
    if not isinstance(features,dict) or str(features.get("sport") or "").lower()!="nfl": raise SystemExit("NFL_FORWARD_LIVE_FEATURE_PAYLOAD_INVALID")
    source_hash=str(features.get("source_manifest_sha256") or "").strip().lower()
    if len(source_hash)!=64: raise SystemExit("NFL_FORWARD_LIVE_FEATURE_SOURCE_HASH_INVALID")
    feature_asof=_dt(features.get("asof_ts"),"NFL_FORWARD_LIVE_FEATURE_ASOF_INVALID")
    if feature_asof>captured: raise SystemExit("NFL_FORWARD_LIVE_FEATURE_FROM_FUTURE")
    games=features.get("games")
    if not isinstance(games,list) or not games: raise SystemExit("NFL_FORWARD_LIVE_FEATURE_GAMES_EMPTY")
    events=_events(_json(odds_path)); existing_games={str(x.get("game_id") or "") for x in decisions}
    pending_games=[]
    for raw in games:
        if not isinstance(raw,dict): raise SystemExit("NFL_FORWARD_LIVE_FEATURE_GAME_INVALID")
        gid=str(raw.get("game_id") or "").strip()
        if not gid: raise SystemExit("NFL_FORWARD_LIVE_FEATURE_GAME_ID_MISSING")
        if gid in existing_games:
            prior=[x for x in decisions if str(x.get("game_id") or "")==gid]
            if len(prior)!=3: raise SystemExit(f"NFL_FORWARD_STATE_PARTIAL_GAME_DECISION:{gid}")
            continue
        pending_games.append(raw)

    added=[]
    if pending_games:
        identity={"code_git_sha":model_sha,"model_id":artifact.get("model_id"),"feature_contract":artifact.get("feature_contract"),"model_artifact_sha256":model_hash}
        canonical_features=dict(features)
        canonical_features["games"]=pending_games
        try:
            added=run_canonical_nfl_live(
                model=model,
                live_features=canonical_features,
                odds_events=events,
                captured_at=captured,
                identity=identity,
            )
        except ValueError as exc:
            raise _canonical_live_error(exc) from exc
        decisions.extend(added)

    _assert_unique(decisions,"DECISION"); _write_jsonl(decisions_path,decisions)
    return {"schema_version":1,"added_decisions":len(added),"qualifying_added":sum(str(x.get("gate_result")) in _PROMOTION_GATES for x in added),"decision_row_count":len(decisions),"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash}


def close_mode(state_dir: Path, model_path: Path, odds_dir: Path, captured: datetime) -> dict[str,Any]:
    decisions_path,closes_path,_=_state_paths(state_dir)
    decisions=_jsonl(decisions_path); closes=_jsonl(closes_path); _assert_unique(decisions,"DECISION"); _assert_unique(closes,"CLOSE")
    _,model_sha,model_hash=_release(model_path); _bind_release(state_dir,model_sha,model_hash)
    closed={_key(x) for x in closes}; added=[]; unresolved=[]
    groups={}
    for row in decisions:
        if str(row.get("gate_result") or "") not in _PROMOTION_GATES or _key(row) in closed: continue
        event_id=str(row.get("provider_event_id") or "").strip()
        if not event_id: raise SystemExit("NFL_FORWARD_STATE_PROVIDER_EVENT_ID_MISSING")
        groups.setdefault(event_id,[]).append(row)
    for event_id,rows in groups.items():
        path=odds_dir/f"{event_id}.json"
        if not path.exists(): continue
        event=_json(path)
        if not isinstance(event,dict): raise SystemExit(f"NFL_FORWARD_CLOSE_EVENT_INVALID:{event_id}")
        for decision in rows:
            if _key(decision) in closed: continue
            try:
                generated=build_forward_close_rows([decision],event,captured_at=captured)
            except ValueError as exc:
                if str(exc)=="NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING":
                    unresolved.append({"key":_key(decision),"reason":str(exc)})
                    continue
                raise
            if len(generated)!=1: raise SystemExit("NFL_FORWARD_CLOSE_ROW_COUNT_INVALID")
            row=generated[0]
            row["model_artifact_sha256"]=model_hash
            row["live_feature_source_manifest_sha256"]=decision.get("live_feature_source_manifest_sha256")
            closes.append(row); added.append(row); closed.add(_key(row))
    _assert_unique(closes,"CLOSE"); _write_jsonl(closes_path,closes)
    return {"schema_version":1,"added_closes":len(added),"unresolved_original_threshold":len(unresolved),"unresolved":unresolved,"close_row_count":len(closes),"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash}


def export_mode(state_dir: Path, out_dir: Path) -> dict[str,Any]:
    decisions_path,closes_path,_=_state_paths(state_dir)
    decisions=_jsonl(decisions_path); closes=_jsonl(closes_path); _assert_unique(decisions,"DECISION"); _assert_unique(closes,"CLOSE")
    close_map={_key(x):x for x in closes}
    complete=[x for x in decisions if str(x.get("gate_result") or "") in _PROMOTION_GATES and _key(x) in close_map]
    complete_closes=[close_map[_key(x)] for x in complete]
    out_dir.mkdir(parents=True,exist_ok=True)
    if complete:
        _write_jsonl(out_dir/"nfl_forward_decisions.jsonl",complete)
        _write_jsonl(out_dir/"nfl_forward_closes.jsonl",complete_closes)
    return {"schema_version":1,"complete_pair_count":len(complete),"complete_market_counts":{m:sum(str(x.get("market") or "").lower()==m for x in complete) for m in ("moneyline","spread","total")}}


def main()->int:
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    common=lambda q: q.add_argument("--state-dir",type=Path,required=True)
    q=sub.add_parser("plan"); common(q); q.add_argument("--schedule-file",type=Path,required=True); q.add_argument("--now",required=True); q.add_argument("--decision-min-lead",type=int,default=45); q.add_argument("--decision-max-lead",type=int,default=120); q.add_argument("--close-min-lead",type=int,default=2); q.add_argument("--close-max-lead",type=int,default=20); q.add_argument("--out",type=Path)
    q=sub.add_parser("decision"); common(q); q.add_argument("--model-artifact",type=Path,required=True); q.add_argument("--live-features",type=Path,required=True); q.add_argument("--odds",type=Path,required=True); q.add_argument("--captured-at",required=True); q.add_argument("--out",type=Path)
    q=sub.add_parser("close"); common(q); q.add_argument("--model-artifact",type=Path,required=True); q.add_argument("--odds-dir",type=Path,required=True); q.add_argument("--captured-at",required=True); q.add_argument("--out",type=Path)
    q=sub.add_parser("export"); common(q); q.add_argument("--out-dir",type=Path,required=True); q.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.command=="plan": result=plan(a.schedule_file,a.state_dir,_dt(a.now,"NFL_FORWARD_PLAN_NOW_INVALID"),decision_min=a.decision_min_lead,decision_max=a.decision_max_lead,close_min=a.close_min_lead,close_max=a.close_max_lead)
    elif a.command=="decision": result=decision_mode(a.state_dir,a.model_artifact,a.live_features,a.odds,_dt(a.captured_at,"NFL_FORWARD_CAPTURED_AT_INVALID"))
    elif a.command=="close": result=close_mode(a.state_dir,a.model_artifact,a.odds_dir,_dt(a.captured_at,"NFL_FORWARD_CAPTURED_AT_INVALID"))
    else: result=export_mode(a.state_dir,a.out_dir)
    text=json.dumps(result,sort_keys=True)
    if getattr(a,"out",None): a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(text); return 0

if __name__=="__main__": raise SystemExit(main())