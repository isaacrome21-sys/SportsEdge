#!/usr/bin/env python3
"""Capture outcomeless pregame Pitcher BB V6 forward-shadow predictions."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib, json, math, os
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import joblib
import numpy as np

import scripts.rebuild_pitcher_bb_v4 as v4
from sportsedge.forward_shadow import ShadowPrediction, canonical_json, write_prediction_ledger
from sportsedge.historical_cutoff import suspended_or_resumed_reason
from sportsedge.mlb_source import BASE, _get_json, fetch_boxscore, fetch_schedule, parse_game_start

CT=ZoneInfo("America/Chicago")
EXPECTED_MODEL_SHA=os.getenv("SPORTSEDGE_BB_V6_SHA256","fa408d9a086f409e073ce811c93b1d47454a43d93cc08143038def793792a9cf")
EXPECTED_BASE_STATE_SHA=os.getenv("SPORTSEDGE_BB_V6_STATE_SHA256","4867110378bce127f316005a7583eb8d213b213dc98a1145d1d9e2f5d0a6215f")


def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _logit(p):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6); return np.log(p/(1-p))

def _state_sha(state)->str: return hashlib.sha256(canonical_json(state)).hexdigest()

def _schedule_raw(day:date):
    q=urlencode({"sportId":1,"date":day.isoformat(),"gameType":"R","hydrate":"team"})
    return _get_json(f"{BASE}/api/v1/schedule?{q}")

def _bucket(state:dict,key:str,identity:int,defaults:dict):
    table=state.setdefault(key,{})
    return table.setdefault(str(int(identity)),dict(defaults))

def _roll_one_day(state:dict, day:date)->None:
    raw=_schedule_raw(day)
    games=[]
    for block in raw.get("dates") or []:
        for game in block.get("games") or []:
            if (game.get("status") or {}).get("abstractGameState")!="Final": continue
            if suspended_or_resumed_reason(game): continue
            official=str(game.get("officialDate") or block.get("date") or "")
            if official!=day.isoformat(): continue
            games.append(game)
    for game in games:
        pk=int(game["gamePk"]); box=fetch_boxscore(pk); teams=box.get("teams") or {}
        for side in ("away","home"):
            team=teams.get(side) or {}; pid,stats=v4.old.starter(team)
            if pid is None or stats is None: continue
            bf=v4.old.safe(stats,"battersFaced"); bb=v4.old.safe(stats,"baseOnBalls"); er=v4.old.safe(stats,"earnedRuns"); hits=v4.old.safe(stats,"hits")
            if bf<=0: continue
            p=_bucket(state,"pitchers",int(pid),{"starts":0,"bf":0.0,"bb":0.0,"er":0.0,"hits":0.0})
            p["starts"]+=1; p["bf"]+=bf; p["bb"]+=bb; p["er"]+=er; p["hits"]+=hits
            lg=state.setdefault("league",{"bf":0.0,"bb":0.0,"er":0.0})
            lg["bf"]+=bf; lg["bb"]+=bb; lg["er"]+=er
        ids={"away":int(game["teams"]["away"]["team"]["id"]),"home":int(game["teams"]["home"]["team"]["id"])}
        for side,tid in ids.items():
            batting=((teams.get(side) or {}).get("teamStats") or {}).get("batting") or {}
            t=_bucket(state,"teams",tid,{"pa":0.0,"bb":0.0,"runs":0.0,"hits":0.0})
            t["pa"]+=v4.old.safe(batting,"plateAppearances"); t["bb"]+=v4.old.safe(batting,"baseOnBalls")
            t["runs"]+=v4.old.safe(batting,"runs"); t["hits"]+=v4.old.safe(batting,"hits")
    state["cutoff"]=day.isoformat(); state["observed_date_max"]=day.isoformat()


def _roll_to_yesterday(base:dict, slate:date)->dict:
    state=json.loads(json.dumps(base))
    cutoff=date.fromisoformat(str(state["cutoff"])); target=slate-timedelta(days=1)
    if cutoff>target: raise RuntimeError("BB_V6_STATE_FROM_FUTURE")
    day=cutoff+timedelta(days=1)
    while day<=target:
        _roll_one_day(state,day); day+=timedelta(days=1)
    return state


def _features(state:dict,pitcher_id:int,opp_id:int,slate:date)->list[float]:
    p=(state.get("pitchers") or {}).get(str(int(pitcher_id))) or {"starts":0,"bf":0.0,"bb":0.0,"er":0.0,"hits":0.0}
    t=(state.get("teams") or {}).get(str(int(opp_id))) or {"pa":0.0,"bb":0.0,"runs":0.0,"hits":0.0}
    lg=state.get("league") or {"bf":0.0,"bb":0.0,"er":0.0}
    league_p_w=(float(lg["bb"])+v4.old.PRIOR_W*12000)/(float(lg["bf"])+12000)
    league_p_er=(float(lg["er"])+v4.old.PRIOR_ER*12000)/(float(lg["bf"])+12000)
    doy=slate.timetuple().tm_yday
    return [
        v4.old.rate(float(p["bb"]),float(p["bf"]),league_p_w,v4.old.PITCHER_PRIOR_BF),
        v4.old.rate(float(p["er"]),float(p["bf"]),league_p_er,v4.old.PITCHER_PRIOR_BF),
        v4.old.rate(float(p["hits"]),float(p["bf"]),v4.old.PRIOR_H,v4.old.PITCHER_PRIOR_BF),
        float(p["bf"])/float(p["starts"]) if float(p["starts"]) else 22.0,
        float(p["starts"]),
        v4.old.rate(float(t["bb"]),float(t["pa"]),v4.old.PRIOR_W,v4.old.TEAM_PRIOR_PA),
        v4.old.rate(float(t["runs"]),float(t["pa"]),v4.old.PRIOR_R,v4.old.TEAM_PRIOR_PA),
        v4.old.rate(float(t["hits"]),float(t["pa"]),v4.old.PRIOR_H,v4.old.TEAM_PRIOR_PA),
        league_p_w,league_p_er,float(slate.month),
        math.sin(2*math.pi*doy/365.25),math.cos(2*math.pi*doy/365.25),
    ]


def main()->int:
    now=datetime.now(timezone.utc); slate=now.astimezone(CT).date()
    root=Path(os.getenv("SPORTSEDGE_BB_V6_OUT","artifacts/bb-v6-shadow"))
    ap=root/"sportsedge_pitcher_bb_v6_shadow.joblib"; sp=root/"bb_v6_base_state.joblib"
    if not ap.is_file() or sha(ap)!=EXPECTED_MODEL_SHA: raise SystemExit("BB_V6_ARTIFACT_SHA_MISMATCH")
    if not sp.is_file() or sha(sp)!=EXPECTED_BASE_STATE_SHA: raise SystemExit("BB_V6_BASE_STATE_SHA_MISMATCH")
    artifact=joblib.load(ap); base_state=joblib.load(sp)
    if artifact.get("deployment_eligible") is not False or artifact.get("model_p_sportsbook_independent") is not True: raise SystemExit("BB_V6_ARTIFACT_CONTRACT_INVALID")
    features=tuple(artifact.get("feature_names") or ())
    if features!=tuple(v4.FEATURES): raise SystemExit("BB_V6_FEATURE_CONTRACT_MISMATCH")
    state=_roll_to_yesterday(base_state,slate); state_digest=_state_sha(state)
    model=artifact["base_model"]; base_cal=artifact["base_calibrator"]; iso=artifact["v6_calibrator"]
    feature_sha=hashlib.sha256(canonical_json(list(features))).hexdigest()
    schedule=fetch_schedule(slate.isoformat(),now=now)
    rows=[]; blocked=[]
    for g in schedule:
        start=parse_game_start(g.game_date)
        if g.status!="Preview" or now>=start: continue
        for side,pid,opp in (("away",g.away_probable_pitcher_id,g.home_id),("home",g.home_probable_pitcher_id,g.away_id)):
            if not pid:
                blocked.append({"game_id":str(g.game_pk),"side":side,"reason":"PROBABLE_PITCHER_UNRESOLVED"}); continue
            x=np.asarray([_features(state,int(pid),int(opp),slate)],float)
            if x.shape[1]!=len(features): raise SystemExit("BB_V6_LIVE_FEATURE_LENGTH_MISMATCH")
            raw=model.predict_proba(x)[:,1]; p0=base_cal.predict_proba(_logit(raw).reshape(-1,1))[:,1]
            over=float(np.clip(iso.predict(p0)[0],.001,.999)); under=1-over
            identity={"pitcher_id":int(pid),"team_side":side,"opponent_team_id":int(opp),"starter_status":"MLB_PROBABLE"}
            provenance={"state_cutoff":str(state["cutoff"]),"state_sha256":state_digest,"base_state_sha256":EXPECTED_BASE_STATE_SHA,"sportsbook_data_used":False}
            for side_name,p in (("OVER",over),("UNDER",under)):
                rows.append(ShadowPrediction(market="PITCHER_BB",game_id=str(g.game_pk),entity_id=str(pid),side=side_name,line=1.5,model_p=p,generated_at_utc=now.isoformat(),cutoff_at_utc=start.isoformat(),model_artifact_sha256=EXPECTED_MODEL_SHA,feature_contract_sha256=feature_sha,source_cutoff=str(state["cutoff"]),model_version="PITCHER_BB_V6_FORWARD_SHADOW",identity=identity,provenance=provenance))
    out=Path("artifacts/forward-shadow/bb_v6_predictions.json"); man=Path("artifacts/forward-shadow/bb_v6_manifest.json")
    write_prediction_ledger(rows,output=out,manifest=man,generated_at=now)
    status={"schema_version":"bb_v6_shadow_capture_v1","generated_at_utc":now.isoformat(),"slate_date_ct":slate.isoformat(),"candidate_sha256":EXPECTED_MODEL_SHA,"base_state_sha256":EXPECTED_BASE_STATE_SHA,"rolled_state_sha256":state_digest,"source_cutoff":str(state["cutoff"]),"predictions":len(rows),"pitchers_predicted":len(rows)//2,"blocked":blocked,"sportsbook_data_used":False,"deployment_eligible":False}
    Path("artifacts/forward-shadow/bb_v6_status.json").write_bytes(canonical_json(status))
    print(json.dumps({"pitchers_predicted":len(rows)//2,"blocked":len(blocked),"source_cutoff":str(state["cutoff"]),"candidate_sha256":EXPECTED_MODEL_SHA},indent=2))
    if not rows: raise SystemExit("BB_V6_SHADOW_NO_PREGAME_PREDICTIONS")
    return 0

if __name__=="__main__": raise SystemExit(main())
