#!/usr/bin/env python3
"""Build a no-outcome-after-cutoff BB state for fast V6 live shadow inference."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib, json, os
from pathlib import Path
import joblib

import scripts.build_pitcher_bb_v6_shadow as v6
import scripts.rebuild_pitcher_bb_v4 as v4

CUTOFF=date(2026,8,12)
OUT=Path(os.getenv("SPORTSEDGE_BB_V6_OUT","artifacts/bb-v6-shadow"))


def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
    root=Path(os.getenv("SPORTSEDGE_BB_V6_CACHE", ".cache/sportsedge/bb-v6-shadow"))
    games,excluded=v6.schedule_through_cutoff(root/"schedule")
    v4.old.ensure_boxes(games,root/"boxscores")
    ps=defaultdict(v4.old.PState); ts=defaultdict(v4.old.TState)
    lg_bf=lg_bb=lg_er=0.0; observed=[]
    for g in games:
        gd=date.fromisoformat(g["officialDate"])
        if gd>CUTOFF: raise RuntimeError("BB_V6_STATE_POST_CUTOFF_GAME")
        p=root/"boxscores"/f"{g['game_pk']}.json"
        if not p.exists(): continue
        try: box=json.loads(p.read_text())
        except Exception: continue
        teams=box.get("teams") or {}; updates=[]
        for side in ("away","home"):
            team=teams.get(side) or {}; pid,st=v4.old.starter(team)
            if pid is None or st is None: continue
            bf=v4.old.safe(st,"battersFaced"); bb=v4.old.safe(st,"baseOnBalls"); er=v4.old.safe(st,"earnedRuns"); hh=v4.old.safe(st,"hits")
            if bf<=0: continue
            updates.append((int(pid),bf,bb,er,hh))
        for side,tid in (("away",g["away_id"]),("home",g["home_id"])):
            bat=((teams.get(side) or {}).get("teamStats") or {}).get("batting") or {}; t=ts[int(tid)]
            t.pa+=v4.old.safe(bat,"plateAppearances"); t.bb+=v4.old.safe(bat,"baseOnBalls"); t.runs+=v4.old.safe(bat,"runs"); t.hits+=v4.old.safe(bat,"hits")
        for pid,bf,bb,er,hh in updates:
            q=ps[pid]; q.starts+=1; q.bf+=bf; q.bb+=bb; q.er+=er; q.hits+=hh
            lg_bf+=bf; lg_bb+=bb; lg_er+=er
        observed.append(g["officialDate"])
    if not observed or max(observed)>CUTOFF.isoformat(): raise RuntimeError("BB_V6_STATE_DATE_BOUND_FAIL")
    payload={
        "schema_version":"bb_v6_base_state_v1","cutoff":"2026-08-12",
        "pitchers":{str(k):{"starts":v.starts,"bf":v.bf,"bb":v.bb,"er":v.er,"hits":v.hits} for k,v in ps.items()},
        "teams":{str(k):{"pa":v.pa,"bb":v.bb,"runs":v.runs,"hits":v.hits} for k,v in ts.items()},
        "league":{"bf":lg_bf,"bb":lg_bb,"er":lg_er},
        "source_games":len(games),"observed_date_max":max(observed),"excluded_source_rows":excluded,
        "sportsbook_data_used":False,"outcomes_after_cutoff_used":False,
    }
    OUT.mkdir(parents=True,exist_ok=True)
    sp=OUT/"bb_v6_base_state.joblib"; joblib.dump(payload,sp,compress=3)
    manifest={"schema_version":"bb_v6_base_state_manifest_v1","state_sha256":sha(sp),"cutoff":"2026-08-12","source_games":len(games),"observed_date_max":max(observed),"sportsbook_data_used":False,"outcomes_after_cutoff_used":False}
    (OUT/"bb_v6_base_state_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print(json.dumps(manifest,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
