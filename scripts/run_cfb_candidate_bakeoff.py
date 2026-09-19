#!/usr/bin/env python3
"""Run the frozen all-four CFB candidate bakeoff exactly once per governed dispatch."""
from __future__ import annotations
import argparse, json
from hashlib import sha1
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from sportsedge.sports.cfb.candidate_bakeoff import evaluate_cfb_candidate_bakeoff
from sportsedge.sports.cfb.candidate_prereg_binding import verify_candidate_prereg_binding

CONFIG=ROOT/"config/cfb_candidate_bakeoff_evaluator_v1.json"
POLICY=ROOT/"config/cfb_model_selection_policy_v1.json"
PREREG=ROOT/"config/cfb_model_candidate_prereg_v1.json"

def _load(p): return json.loads(Path(p).read_text())
def _blob(raw):
    return sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--private-rows",type=Path,required=True)
    ap.add_argument("--selection-bundle",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--confirm",required=True,choices=["CONSUME_ALL_FOUR_CFB_ATTEMPTS"])
    args=ap.parse_args(argv)
    cfg=_load(CONFIG); policy=_load(POLICY); prereg=_load(PREREG)
    if cfg.get("status")!="FROZEN_BEFORE_FIRST_EVALUATION":
        raise SystemExit("CFB_BAKEOFF_EVALUATOR_NOT_FROZEN")
    code=ROOT/str(cfg.get("evaluator_path"))
    if _blob(code.read_bytes())!=cfg.get("evaluator_code_git_blob"):
        raise SystemExit("CFB_BAKEOFF_EVALUATOR_CODE_BLOB_MISMATCH")
    binding=verify_candidate_prereg_binding(root=ROOT)
    if binding.get("status")!="READY_FOR_FIRST_EVALUATION" or binding.get("blockers"):
        raise SystemExit("CFB_BAKEOFF_PREREG_NOT_READY:"+",".join(binding.get("blockers") or []))
    if int(policy.get("attempts_consumed",-1))!=0 or prereg.get("governance",{}).get("attempts_consumed")!=0:
        raise SystemExit("CFB_BAKEOFF_ATTEMPT_BUDGET_NOT_UNSPENT")
    if prereg.get("governance",{}).get("evaluation_performed") is not False:
        raise SystemExit("CFB_BAKEOFF_ALREADY_EVALUATED")
    rows=_load(args.private_rows); bundle=_load(args.selection_bundle)
    if not isinstance(rows,list) or not rows:
        raise SystemExit("CFB_BAKEOFF_PRIVATE_ROWS_MISSING")
    expected=bundle.get("selection_rows_sha256")
    from hashlib import sha256
    raw=json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if sha256(raw).hexdigest()!=expected:
        raise SystemExit("CFB_BAKEOFF_SELECTION_ROWS_HASH_MISMATCH")
    identity={"selection_rows_sha256":expected,
              "source_manifest_sha256":bundle.get("source_manifest_sha256"),
              "predictive_code_manifest_sha256":bundle.get("predictive_code_manifest_sha256"),
              "acquisition_code_manifest_sha256":bundle.get("acquisition_code_manifest_sha256"),
              "evaluator_code_git_blob":cfg.get("evaluator_code_git_blob")}
    result=evaluate_cfb_candidate_bakeoff(rows,cfg,input_identity=identity)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":result["status"],"result_sha256":result["result_sha256"],
                      "winner":result["winner"],"attempt_budget_consumed_by_evaluation":4,
                      "model_p_created":False,"truth_gate_authority":False,
                      "promotion_authority":False,"eligibility_changed":False,
                      "staking_authority":False,"evidence_clock_authority":False,
                      "official_authority":False},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
