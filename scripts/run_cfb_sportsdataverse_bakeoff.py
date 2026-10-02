#!/usr/bin/env python3
"""Governed first evaluation entrypoint for the frozen SportsDataverse CFB lane."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from sportsedge.sports.cfb.sportsdataverse_prereg_hash import CODE_PATHS,CONFIG_PATHS,verify
from sportsedge.sports.cfb.sportsdataverse_bakeoff import evaluate_native_candidates

CONFIRM="CONSUME_ALL_FOUR_CFB_SDV_ATTEMPTS"

def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--rows",required=True)
 ap.add_argument("--prereg",default="config/cfb_sportsdataverse_candidate_prereg_v1.json")
 ap.add_argument("--confirm",required=True)
 ap.add_argument("--out",required=True)
 a=ap.parse_args()
 if a.confirm!=CONFIRM: raise SystemExit("CFB_SDV_ATTEMPT_CONFIRMATION_REQUIRED")
 prereg=json.loads(Path(a.prereg).read_text())
 gov=prereg.get("governance") or {}
 if gov.get("attempts_consumed")!=0 or gov.get("evaluation_performed") is not False:
  raise SystemExit("CFB_SDV_ATTEMPT_BUDGET_NOT_FRESH")
 binding=prereg.get("hash_binding") or {}
 files={p:Path(p).read_text(encoding="utf-8") for p in (*CODE_PATHS,*CONFIG_PATHS)}
 verify(binding.get("code_manifest_sha256",""),binding.get("config_bundle_sha256",""),files)
 rows=json.loads(Path(a.rows).read_text())
 if not isinstance(rows,list) or not rows: raise SystemExit("CFB_SDV_EVALUATION_ROWS_REQUIRED")
 if any(int(r.get("season",9999))>=2026 for r in rows): raise SystemExit("CFB_SDV_2026_OUTCOME_FORBIDDEN")
 result=evaluate_native_candidates(rows,prereg)
 result["governance"]={"attempts_consumed":4,"evaluation_performed":True,"selection_scope_only":True,
  "model_p_created":False,"promotion_authority":False,"official_authority":False}
 Path(a.out).parent.mkdir(parents=True,exist_ok=True)
 Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
 return 0
if __name__=="__main__": raise SystemExit(main())
