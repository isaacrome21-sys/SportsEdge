#!/usr/bin/env python3
"""Build the predeclared Pitcher BB V6 forward-shadow candidate.

This is development only. All observed outcomes are hard-bounded to <= 2026-08-12.
The candidate hash is frozen before 2026-08-13 outcomes are eligible for scoring.
Deployment is always false here; only the separate forward-shadow evaluator can
promote the candidate after the protocol's minimum future evidence is reached.
"""
from __future__ import annotations

from datetime import date
import hashlib, json, math, os
from pathlib import Path

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression

import scripts.rebuild_pitcher_bb_v4 as v4
import scripts.rebuild_pitcher_bb_v4_1 as strict

CUTOFF = date(2026, 8, 12)
BASE_SHA = "67fc9d5c96ab469d888c7e137072d156043eb31fa3576fbe31d97e4436b9e7bc"
PROTOCOL = Path("audit/BB_V6_FORWARD_SHADOW_PROTOCOL_2026-08-13.md")
BASE_ARTIFACT = Path(os.getenv("SPORTSEDGE_BB_V4_ARTIFACT", "phase6_artifacts/sportsedge_pitcher_bb_v4.joblib"))
OUT = Path(os.getenv("SPORTSEDGE_BB_V6_OUT", "artifacts/bb-v6-shadow"))


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda:f.read(1<<20),b""): h.update(c)
    return h.hexdigest()


def logit(p):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return np.log(p/(1-p))


def metric(p,y):
    p=np.asarray(p,float); y=np.asarray(y,int); n=len(y)
    actual=float(y.mean()); pred=float(p.mean())
    se=math.sqrt(max(actual*(1-actual),1e-9)/max(n,1))
    return {
        "n":int(n),"pred":pred,"actual":actual,"gap_pp":100*(pred-actual),
        "z":abs(pred-actual)/se,"brier":float(np.mean((p-y)**2)),
        "log_loss":float(-np.mean(y*np.log(np.clip(p,1e-9,1))+(1-y)*np.log(np.clip(1-p,1e-9,1))))
    }


def schedule_through_cutoff(cache: Path):
    original_years=v4.YEARS; original_ranges=v4.month_ranges
    def ranges(year:int):
        if year!=2026:
            yield from v4.old.month_ranges(year); return
        for month in range(3,8):
            yield f"2026-{month:02d}-01", f"2026-{month:02d}-{__import__('calendar').monthrange(2026,month)[1]:02d}"
        yield "2026-08-01", CUTOFF.isoformat()
    try:
        v4.YEARS=(2021,2022,2023,2024,2025,2026); v4.month_ranges=ranges
        games,excluded=strict.fetch_schedule_strict(cache)
    finally:
        v4.YEARS=original_years; v4.month_ranges=original_ranges
    bad=[g for g in games if date.fromisoformat(g["officialDate"])>CUTOFF]
    if bad: raise RuntimeError("BB_V6_POST_CUTOFF_SCHEDULE_ROW")
    return games,excluded


def main()->int:
    if not PROTOCOL.is_file(): raise RuntimeError("BB_V6_PROTOCOL_MISSING")
    if not BASE_ARTIFACT.is_file(): raise RuntimeError("BB_V4_ARTIFACT_MISSING")
    if sha(BASE_ARTIFACT)!=BASE_SHA: raise RuntimeError("BB_V4_ARTIFACT_SHA_MISMATCH")
    frozen=joblib.load(BASE_ARTIFACT)
    model=frozen["models"]["1.5"]["model"]; cal=frozen["models"]["1.5"]["calibrator"]

    root=Path(os.getenv("SPORTSEDGE_BB_V6_CACHE", ".cache/sportsedge/bb-v6-shadow"))
    games,excluded=schedule_through_cutoff(root/"schedule")
    v4.old.ensure_boxes(games,root/"boxscores")
    X,walks,years,ids=v4.build_cutoff(games,root/"boxscores")
    by_date={int(g["game_pk"]):g["officialDate"] for g in games}
    dates=np.asarray([by_date[int(x[0])] for x in ids])
    if len(dates)==0 or max(dates)>CUTOFF.isoformat(): raise RuntimeError("BB_V6_FEATURE_CUTOFF_VIOLATION")

    raw=model.predict_proba(X)[:,1]
    base=cal.predict_proba(logit(raw).reshape(-1,1))[:,1]
    y=(walks>1.5).astype(int)
    # Use recent already-observed seasons for calibration development. This is
    # not called holdout evidence; future promotion starts 2026-08-13 only.
    dev=(years>=2025) & (dates<=CUTOFF.isoformat())
    if int(dev.sum())<1000: raise RuntimeError("BB_V6_DEVELOPMENT_SAMPLE_TOO_SMALL")
    iso=IsotonicRegression(y_min=.001,y_max=.999,increasing=True,out_of_bounds="clip")
    iso.fit(base[dev],y[dev])
    p=np.asarray(iso.predict(base[dev]),float)
    if np.any(np.diff(np.asarray(iso.X_thresholds_,float))<=0): raise RuntimeError("BB_V6_ISOTONIC_X_NOT_STRICT")
    if np.any(np.diff(np.asarray(iso.y_thresholds_,float))<0): raise RuntimeError("BB_V6_ISOTONIC_NOT_MONOTONE")

    protocol_sha=sha(PROTOCOL)
    artifact={
        "version":"PITCHER_BB_V6_FORWARD_SHADOW",
        "deployment_eligible":False,
        "deployment_block_reason":"FORWARD_SHADOW_INSUFFICIENT_SAMPLE",
        "development_cutoff":"2026-08-12",
        "forward_shadow_start":"2026-08-13",
        "base_artifact_sha256":BASE_SHA,
        "base_version":str((frozen.get("metadata") or {}).get("version") or "PITCHER_BB_V4"),
        "feature_names":tuple(v4.FEATURES),
        "threshold":1.5,
        "base_model":model,
        "base_calibrator":cal,
        "v6_calibrator":iso,
        "calibration_form":"ISOTONIC_MONOTONE_INCREASING",
        "probability_bounds":[.001,.999],
        "protocol_sha256":protocol_sha,
        "model_p_sportsbook_independent":True,
    }
    OUT.mkdir(parents=True,exist_ok=True)
    ap=OUT/"sportsedge_pitcher_bb_v6_shadow.joblib"; joblib.dump(artifact,ap,compress=3)
    report={
        "schema_version":"pitcher_bb_v6_shadow_development_v1",
        "artifact_sha256":sha(ap),"protocol_sha256":protocol_sha,"base_artifact_sha256":BASE_SHA,
        "development_cutoff":"2026-08-12","forward_shadow_start":"2026-08-13",
        "development_rows":int(dev.sum()),"development_metric":metric(p,y[dev]),
        "base_development_metric":metric(base[dev],y[dev]),
        "observed_date_max":str(max(dates)),"excluded_source_rows":excluded,
        "deployment_eligible":False,"deployment_block_reason":"FORWARD_SHADOW_INSUFFICIENT_SAMPLE",
        "outcomes_after_cutoff_used":False,"sportsbook_data_used":False,
    }
    (OUT/"validation.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:report[k] for k in ("artifact_sha256","development_rows","development_metric","deployment_eligible","deployment_block_reason")},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
