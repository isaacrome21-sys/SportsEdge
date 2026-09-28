#!/usr/bin/env python3
"""Fail-closed coverage audit for the preregistered NFL QB/injury mixture lane."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

INJ_REQUIRED={"season","week","position","report_status"}
ROSTER_REQUIRED={"season","week","position","team"}
PIT_CANDIDATES=("date_modified","report_date","timestamp")
ID_CANDIDATES=("gsis_id","player_id","full_name")

def _read(paths, required, error):
    frames=[]
    for path in paths:
        df=pd.read_csv(path)
        missing=sorted(required-set(df.columns))
        if missing: raise SystemExit(error+":"+",".join(missing))
        frames.append(df)
    return pd.concat(frames,ignore_index=True)

def _player_key(df):
    for c in ID_CANDIDATES:
        if c in df.columns:
            return df[c].astype(str)
    raise SystemExit("QB_INJURY_COVERAGE_PLAYER_ID_MISSING")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,nargs="+",required=True)
    p.add_argument("--weekly-rosters",type=Path,nargs="+",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    inj=_read(a.input,INJ_REQUIRED,"QB_INJURY_COVERAGE_REQUIRED_FIELD_MISSING")
    ros=_read(a.weekly_rosters,ROSTER_REQUIRED,"QB_ROSTER_COVERAGE_REQUIRED_FIELD_MISSING")
    for df in (inj,ros):
        df["season"]=pd.to_numeric(df["season"],errors="coerce")
        df["week"]=pd.to_numeric(df["week"],errors="coerce")
    inj=inj[inj["position"].astype(str).str.upper().eq("QB")].copy()
    ros=ros[ros["position"].astype(str).str.upper().eq("QB")].copy()
    inj["_player_key"]=_player_key(inj); ros["_player_key"]=_player_key(ros)
    required_seasons=set(range(2009,2026))
    missing_seasons=sorted(required_seasons-set(inj["season"].dropna().astype(int)))
    timestamp_cols=[c for c in PIT_CANDIDATES if c in inj.columns]
    pit_nonnull={c:int(inj[c].notna().sum()) for c in timestamp_cols}
    inj_keys=set(zip(inj["season"],inj["week"],inj["_player_key"]))
    ros=ros[ros["season"].isin(required_seasons) & ros["week"].between(1,18,inclusive="both")]
    roster_keys=set(zip(ros["season"],ros["week"],ros["_player_key"]))
    unmatched=sorted(roster_keys-inj_keys,key=lambda x:(x[0],x[1],x[2]))
    by_week={}
    for s,w,_ in unmatched:
        by_week[f"{int(s)}-{int(w):02d}"]=by_week.get(f"{int(s)}-{int(w):02d}",0)+1
    # Missing injury rows are not proof of health. They remain MISSING.
    fail=bool(missing_seasons or not timestamp_cols or not any(pit_nonnull.values()) or unmatched)
    out={
      "schema":"NFL_QB_INJURY_COVERAGE_AUDIT_V3",
      "status":"FAIL_CLOSED" if fail else "DENOMINATOR_RECONCILED_NOT_MODEL_ADMITTED",
      "required_seasons":[2009,2025],
      "missing_injury_seasons":missing_seasons,
      "pit_timestamp_columns_present":timestamp_cols,
      "pit_timestamp_nonnull_rows":pit_nonnull,
      "weekly_roster_qb_keys":len(roster_keys),
      "injury_qb_keys":len(inj_keys),
      "roster_qb_keys_without_injury_row":len(unmatched),
      "unmatched_by_season_week":by_week,
      "missing_state_policy":"ROSTER_QB_WITHOUT_PIT_INJURY_ROW_IS_MISSING_NOT_AVAILABLE",
      "development_validation_scoring_authority":False
    }
    a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    if fail: raise SystemExit("QB_INJURY_COVERAGE_AUDIT_FAILED")

if __name__=="__main__": main()
