#!/usr/bin/env python3
"""Cumulative Pitcher BB V6 settlement and frozen-gate scoring.

Prediction captures remain immutable. This scorer selects one deterministic
pregame OVER/UNDER pair per pitcher/game, joins official MLB boxscore walks only
after games are Final, and emits a cumulative eligibility report.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.request import urlopen

EXPECTED_MODEL_SHA=os.getenv("SPORTSEDGE_BB_V6_SHA256","fa408d9a086f409e073ce811c93b1d47454a43d93cc08143038def793792a9cf")
SHADOW_START=date(2026,8,13)
MIN_AGE_DAYS=14
MIN_ROWS=150
MIN_COVERAGE=.90
MAX_ABS_Z=2.00
BUCKET_MAX_ABS_Z=2.50
BRIER_TOL=.0010
LOGLOSS_TOL=.0020
BUCKETS=((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.0000001))


def canonical(v:Any)->bytes:
    return (json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True)+"\n").encode()

def parse_dt(v:str)->datetime:
    d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)

def load(path:Path)->Any: return json.loads(path.read_text())
def sha(v:bytes)->str: return hashlib.sha256(v).hexdigest()

def fetch_pitcher_walks(game_id:str,pitcher_id:str)->dict[str,Any]|None:
    try:
        with urlopen(f"https://statsapi.mlb.com/api/v1/game/{int(game_id)}/boxscore",timeout=20) as r:
            box=json.loads(r.read().decode())
        with urlopen(f"https://statsapi.mlb.com/api/v1.1/game/{int(game_id)}/feed/live",timeout=20) as r:
            feed=json.loads(r.read().decode())
    except Exception:
        return None
    status=(((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState"))
    if status!="Final": return None
    key="ID"+str(int(pitcher_id))
    for side in ("away","home"):
        p=((((box.get("teams") or {}).get(side) or {}).get("players") or {}).get(key) or {})
        stats=((p.get("stats") or {}).get("pitching") or {})
        if stats:
            try: walks=int(stats.get("baseOnBalls") or 0)
            except Exception: return None
            return {"game_id":str(game_id),"pitcher_id":str(pitcher_id),"walks":walks,"over_1_5":int(walks>1.5),"source":"MLB_STATSAPI_BOX_SCORE","settled_at_utc":datetime.now(timezone.utc).isoformat()}
    return None

def zstat(ps,ys):
    if not ps:return None
    den=sum(p*(1-p) for p in ps)
    return None if den<=0 else sum(y-p for p,y in zip(ps,ys))/math.sqrt(den)
def brier(ps,ys): return None if not ps else sum((p-y)**2 for p,y in zip(ps,ys))/len(ps)
def ll(ps,ys):
    if not ps:return None
    s=0
    for p,y in zip(ps,ys):
        q=min(max(float(p),1e-12),1-1e-12); s+=-(y*math.log(q)+(1-y)*math.log(1-q))
    return s/len(ps)

def valid(row,violations):
    try:g=parse_dt(row["generated_at_utc"]); c=parse_dt(row["cutoff_at_utc"])
    except Exception: violations.append("BAD_TIME"); return False
    if g>=c: violations.append("CHRONOLOGY"); return False
    if row.get("model_artifact_sha256")!=EXPECTED_MODEL_SHA: violations.append("MODEL_SHA"); return False
    if row.get("market")!="PITCHER_BB" or float(row.get("line"))!=1.5:return False
    if row.get("outcome") is not None: violations.append("MUTATED_PREDICTION"); return False
    if (row.get("provenance") or {}).get("sportsbook_data_used") is True: violations.append("SPORTSBOOK_CONTAMINATION"); return False
    if str((row.get("identity") or {}).get("pitcher_id"))!=str(row.get("entity_id")): violations.append("PITCHER_IDENTITY"); return False
    return True

def main()->int:
    inp=Path(os.getenv("SPORTSEDGE_BB_V6_INPUT","artifacts/bb-forward-shadow-state/captures"))
    out=Path(os.getenv("SPORTSEDGE_BB_V6_SCORE_OUT","artifacts/bb-forward-shadow-state/scored")); out.mkdir(parents=True,exist_ok=True)
    files=sorted(inp.rglob("bb_v6_predictions.json")); statuses=sorted(inp.rglob("bb_v6_status.json"))
    if not files: raise SystemExit("BB_V6_NO_CAPTURE_ARTIFACTS")
    violations=[]; by=defaultdict(list); source_available=set()
    for p in files:
        for r in load(p):
            if not isinstance(r,dict) or not valid(r,violations): continue
            k=(str(r["game_id"]),str(r["entity_id"]),str(r["side"]).upper()); by[k].append(r)
            source_available.add((str(r["game_id"]),str(r["entity_id"])))
    for p in statuses:
        try:s=load(p)
        except Exception: violations.append("BAD_STATUS"); continue
        if s.get("sportsbook_data_used") is True: violations.append("SPORTSBOOK_STATUS_TRUE")
    selected={}
    for gid,pid in sorted({(a,b) for a,b,_ in by}):
        pair={}
        for side in ("OVER","UNDER"):
            rows=by.get((gid,pid,side),[])
            if rows:
                rows.sort(key=lambda r:(parse_dt(r["generated_at_utc"]),str(r.get("row_id") or ""))); pair[side]=rows[0]
        if set(pair)!={"OVER","UNDER"}: violations.append(f"PAIR_MISSING:{gid}:{pid}"); continue
        if abs(float(pair["OVER"]["model_p"])+float(pair["UNDER"]["model_p"])-1)>1e-9: violations.append(f"COMPLEMENT:{gid}:{pid}"); continue
        selected[(gid,pid)]=pair
    sp=out/"bb_v6_settlements.json"; prior={}
    if sp.exists():
        try: prior={(str(x["game_id"]),str(x["pitcher_id"])):x for x in load(sp)}
        except Exception: prior={}
    settlements=dict(prior)
    for key in sorted(selected):
        if key not in settlements:
            o=fetch_pitcher_walks(*key)
            if o is not None:settlements[key]=o
    settled=[settlements[k] for k in sorted(settlements) if k in selected]; sp.write_bytes(canonical(settled))
    ps=[];ys=[];paired=[];baseps=[];evidence=[]
    for key in sorted(selected):
        o=settlements.get(key)
        if o is None:continue
        r=selected[key]["OVER"]; p=float(r["model_p"]); y=int(o["over_1_5"]); ps.append(p);ys.append(y)
        base=(r.get("provenance") or {}).get("base_v4_over_1_5_p")
        if base is not None:
            try:
                q=float(base)
                if 0<q<1: paired.append((p,y)); baseps.append(q)
            except Exception:pass
        evidence.append({"game_id":key[0],"pitcher_id":key[1],"model_p":p,"walks":o["walks"],"outcome":y})
    buckets=[]; bucket_pass=True
    for lo,hi in BUCKETS:
        idx=[i for i,p in enumerate(ps) if lo<=p<hi]; bp=[ps[i] for i in idx]; byy=[ys[i] for i in idx]; z=zstat(bp,byy); app=len(idx)>=75; ok=(not app) or (z is not None and abs(z)<=BUCKET_MAX_ABS_Z); bucket_pass &= ok; buckets.append({"range":[lo,min(hi,1)],"n":len(idx),"z":z,"applicable":app,"pass":ok})
    pps=[x[0] for x in paired]; pys=[x[1] for x in paired]
    v6b=brier(pps,pys); v4b=brier(baseps,pys); v6l=ll(pps,pys); v4l=ll(baseps,pys)
    coverage=len(selected)/len(source_available) if source_available else 0
    age=(datetime.now(timezone.utc).date()-SHADOW_START).days
    gates={
      "age_days":{"value":age,"minimum":MIN_AGE_DAYS,"pass":age>=MIN_AGE_DAYS},
      "settled_pitchers":{"value":len(ps),"minimum":MIN_ROWS,"pass":len(ps)>=MIN_ROWS},
      "overall_calibration":{"z":zstat(ps,ys),"max_abs":MAX_ABS_Z,"pass":zstat(ps,ys) is not None and abs(zstat(ps,ys))<=MAX_ABS_Z},
      "probability_buckets":{"buckets":buckets,"pass":bucket_pass},
      "paired_brier":{"v6":v6b,"v4":v4b,"n":len(pps),"tolerance":BRIER_TOL,"pass":v6b is not None and v4b is not None and v6b<=v4b+BRIER_TOL},
      "paired_logloss":{"v6":v6l,"v4":v4l,"n":len(pps),"tolerance":LOGLOSS_TOL,"pass":v6l is not None and v4l is not None and v6l<=v4l+LOGLOSS_TOL},
      "coverage":{"value":coverage,"minimum":MIN_COVERAGE,"pass":coverage>=MIN_COVERAGE},
      "integrity":{"violations":sorted(set(violations)),"pass":not violations},
    }
    eligible=all(x["pass"] for x in gates.values())
    report={"schema_version":"bb_v6_forward_shadow_evaluation_v1","generated_at_utc":datetime.now(timezone.utc).isoformat(),"candidate_sha256":EXPECTED_MODEL_SHA,"selected_unique_pitchers":len(selected),"settled_unique_pitchers":len(ps),"sportsbook_data_used":False,"market":{"PITCHER_BB":{"eligible":eligible}},"gates":gates,"evidence":evidence,"state":"MODEL_ELIGIBLE" if eligible else "MODEL_NOT_ELIGIBLE"}
    rp=out/"bb_v6_forward_shadow_report.json"; rp.write_bytes(canonical(report)); (out/"bb_v6_forward_shadow_manifest.json").write_bytes(canonical({"report_sha256":sha(rp.read_bytes()),"settlement_sha256":sha(sp.read_bytes()),"eligible":eligible,"candidate_sha256":EXPECTED_MODEL_SHA}))
    print(json.dumps({"state":report["state"],"settled":len(ps),"coverage":coverage,"violations":len(set(violations))},indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
