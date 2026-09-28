#!/usr/bin/env python3
"""Fail-closed coverage audit for the preregistered NFL QB/injury mixture lane."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

REQUIRED = {"season", "week", "position", "report_status"}
PIT_CANDIDATES = ("date_modified", "report_date", "timestamp")

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
    df=df[df["position"].astype(str).str.upper().eq("QB")].copy()
    df["season"]=pd.to_numeric(df["season"],errors="coerce")
    df["week"]=pd.to_numeric(df["week"],errors="coerce")
    required_seasons=set(range(2009,2026))
    seasons=set(df["season"].dropna().astype(int))
    missing_seasons=sorted(required_seasons-seasons)
    timestamp_cols=[c for c in PIT_CANDIDATES if c in df.columns]
    season_week_counts=(
        df.dropna(subset=["season","week"]).assign(
            season=lambda x:x["season"].astype(int), week=lambda x:x["week"].astype(int)
        ).groupby(["season","week"]).size().to_dict()
    )
    missing_regular_weeks={}
    for season in sorted(required_seasons):
        # Audit presence only; do not assume a missing weekly injury row means healthy.
        absent=[w for w in range(1,19) if season_week_counts.get((season,w),0)==0]
        if absent:
            missing_regular_weeks[str(season)]=absent
    pit_nonnull={}
    for c in timestamp_cols:
        pit_nonnull[c]=int(df[c].notna().sum())
    fail=bool(missing_seasons or missing_regular_weeks or not timestamp_cols or not any(pit_nonnull.values()))
    out={
      "schema":"NFL_QB_INJURY_COVERAGE_AUDIT_V2",
      "status":"FAIL_CLOSED" if fail else "COVERAGE_PRESENT_NOT_MODEL_ADMITTED",
      "required_seasons":[2009,2025],
      "missing_seasons":missing_seasons,
      "missing_regular_season_weeks":missing_regular_weeks,
      "pit_timestamp_columns_present":timestamp_cols,
      "pit_timestamp_nonnull_rows":pit_nonnull,
      "qb_rows":int(len(df)),
      "warning":"Presence audit is not proof that all NFL QBs were represented; roster/depth-chart denominator reconciliation is required before modeling.",
      "development_validation_scoring_authority":False
    }
    a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    if fail:
        raise SystemExit("QB_INJURY_COVERAGE_AUDIT_FAILED")

if __name__=="__main__":
    main()
