#!/usr/bin/env python3
"""Fail-closed coverage audit for the preregistered NFL QB/injury mixture lane."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

QB = {"QB"}
REQUIRED = {"season", "week", "position", "report_status"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    a=p.parse_args()
    frames=[]
    for path in a.input:
        df=pd.read_csv(path)
        missing=sorted(REQUIRED-set(df.columns))
        if missing:
            raise SystemExit("QB_INJURY_COVERAGE_REQUIRED_FIELD_MISSING:"+",".join(missing))
        frames.append(df)
    df=pd.concat(frames, ignore_index=True)
    df=df[df["position"].astype(str).str.upper().isin(QB)].copy()
    seasons=set(pd.to_numeric(df["season"], errors="coerce").dropna().astype(int))
    required=set(range(2009, 2026))
    missing_seasons=sorted(required-seasons)
    timestamp_cols=[c for c in ("date_modified","report_date","timestamp") if c in df.columns]
    out={
      "schema":"NFL_QB_INJURY_COVERAGE_AUDIT_V1",
      "status":"FAIL_CLOSED" if missing_seasons or not timestamp_cols else "COVERAGE_PRESENT_NOT_MODEL_ADMITTED",
      "required_seasons":[2009,2025],
      "missing_seasons":missing_seasons,
      "pit_timestamp_columns_present":timestamp_cols,
      "qb_rows":int(len(df)),
      "development_validation_scoring_authority":False
    }
    a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    if out["status"]=="FAIL_CLOSED":
        raise SystemExit("QB_INJURY_COVERAGE_AUDIT_FAILED")

if __name__=="__main__":
    main()
