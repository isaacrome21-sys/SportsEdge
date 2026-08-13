#!/usr/bin/env python3
"""Build only the rolling Statcast state through end-2025 for live V5 inference.

The production GAME model and frozen contact transformer are downloaded from the
already-earned strict holdout artifact. This script does not fit, select,
calibrate, or score any model and never reads sportsbook data. It reconstructs
only team/pitcher/batter rolling contact state from official 2021-2025 Savant
contact rows using the frozen transformer.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib

import scripts.rebuild_statcast_v5_split_v2 as transport
from sportsedge.statcast_v5_data import V5State
from sportsedge.statcast_v5_live import build_prior_state

YEARS=(2021,2022,2023,2024,2025)


def sha(path: Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main()->int:
    root=Path(os.getenv('SPORTSEDGE_STATCAST_V5_OUT','artifacts/statcast-v5-game'))
    cache=Path(os.getenv('SPORTSEDGE_STATCAST_V5_CACHE','.cache/sportsedge/statcast-v5-split'))
    root.mkdir(parents=True,exist_ok=True)
    tp=root/'sportsedge_contact_transformer_v1.joblib'
    if not tp.is_file(): raise SystemExit('STATCAST_V5_FROZEN_TRANSFORMER_MISSING')
    expected=os.getenv('SPORTSEDGE_EXPECTED_V5_TRANSFORMER_SHA256','')
    got=sha(tp)
    if expected and got!=expected: raise SystemExit('STATCAST_V5_FROZEN_TRANSFORMER_SHA_MISMATCH:'+got)
    transformer=joblib.load(tp)
    state=V5State(); source_manifest=[]; counts={}
    bounds=cache/'statsapi-bounds'
    for year in YEARS:
        rows,manifest=transport.fetch_feed(year,'contact',cache/'savant'/str(year),bounds)
        if any(not r.is_contact for r in rows): raise SystemExit(f'STATCAST_STATE_NONCONTACT:{year}')
        # build_prior_state groups by official game date/game and applies only
        # the already locally bounded contact rows.
        state=build_prior_state(rows,transformer,initial_state=state)
        source_manifest.extend(manifest); counts[str(year)]=len(rows)
        print(f'STATCAST_STATE_YEAR_OK year={year} contacts={len(rows)}',flush=True)
    sp=root/'sportsedge_statcast_state_end_2025.joblib'
    joblib.dump(state,sp,compress=3)
    record={
        'schema_version':'sportsedge_statcast_v5_base_state_v1',
        'years':list(YEARS),'contact_rows_by_year':counts,
        'contact_transformer_sha256':got,
        'base_state_end_2025_sha256':sha(sp),
        'source_manifest':source_manifest,
        'model_refit_performed':False,'sportsbook_data_used':False,
    }
    mp=root/'base_state_manifest.json'; mp.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:record[k] for k in ('base_state_end_2025_sha256','contact_rows_by_year','model_refit_performed')},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
