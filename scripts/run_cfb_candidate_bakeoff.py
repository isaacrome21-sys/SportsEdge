#!/usr/bin/env python3
"""Run the frozen all-four CFB candidate bakeoff exactly once per governed dispatch."""
from __future__ import annotations
import argparse, json, os
from hashlib import sha1, sha256
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from sportsedge.sports.cfb.candidate_bakeoff_v3 import evaluate_cfb_candidate_bakeoff_v3
from sportsedge.sports.cfb.candidate_prereg_binding import verify_candidate_prereg_binding

CONFIG=ROOT/"config/cfb_candidate_bakeoff_evaluator_v3.json"
POLICY=ROOT/"config/cfb_model_selection_policy_v1.json"
PREREG=ROOT/"config/cfb_model_candidate_prereg_v1.json"
DISPERSION_PREREG=ROOT/"config/cfb_dispersion_only_prereg_v1.json"


def _load(p): return json.loads(Path(p).read_text())
def _blob(raw): return sha1(f"blob {len(raw)}\0".encode()+raw).hexdigest()

def _verify_v3_bindings(cfg, dispersion_prereg):
    if cfg.get("status")!="FROZEN_BEFORE_FIRST_EVALUATION":
        raise SystemExit("CFB_BAKEOFF_EVALUATOR_NOT_FROZEN")
    code=ROOT/str(cfg.get("evaluator_path"))
    if _blob(code.read_bytes())!=cfg.get("evaluator_code_git_blob"):
        raise SystemExit("CFB_BAKEOFF_EVALUATOR_CODE_BLOB_MISMATCH")
    for rel,expected in (cfg.get("dependency_blobs") or {}).items():
        path=ROOT/str(rel)
        if not path.is_file() or _blob(path.read_bytes())!=expected:
            raise SystemExit("CFB_BAKEOFF_DEPENDENCY_BLOB_MISMATCH:"+str(rel))
    if dispersion_prereg.get("status")!="FROZEN_BEFORE_DISPERSION_EVALUATION":
        raise SystemExit("CFB_DISPERSION_PREREG_NOT_FROZEN")
    bindings=dispersion_prereg.get("bindings") or {}
    v3cfg=bindings.get("bakeoff_v3_config") or {}
    v3eval=bindings.get("bakeoff_v3_evaluator") or {}
    if v3cfg.get("git_blob")!=_blob(CONFIG.read_bytes()):
        raise SystemExit("CFB_DISPERSION_PREREG_V3_CONFIG_BINDING_MISMATCH")
    if v3eval.get("git_blob")!=cfg.get("evaluator_code_git_blob"):
        raise SystemExit("CFB_DISPERSION_PREREG_V3_EVALUATOR_BINDING_MISMATCH")


def _assert_private_capture_path(path: Path):
    resolved=path.resolve()
    root=ROOT.resolve()
    if resolved==root or root in resolved.parents:
        raise SystemExit("CFB_BAKEOFF_CAPTURE_PUBLIC_REPO_PATH_FORBIDDEN")


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("--private-rows",type=Path,required=True)
    ap.add_argument("--selection-bundle",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--private-capture-out",type=Path,required=True)
    ap.add_argument("--confirm",required=True,choices=["CONSUME_ALL_FOUR_CFB_ATTEMPTS"])
    args=ap.parse_args(argv)
    _assert_private_capture_path(args.private_capture_out)

    cfg=_load(CONFIG); policy=_load(POLICY); prereg=_load(PREREG); dispersion_prereg=_load(DISPERSION_PREREG)
    _verify_v3_bindings(cfg,dispersion_prereg)
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
    raw=json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if sha256(raw).hexdigest()!=expected:
        raise SystemExit("CFB_BAKEOFF_SELECTION_ROWS_HASH_MISMATCH")
    identity={"selection_rows_sha256":expected,
              "source_manifest_sha256":bundle.get("source_manifest_sha256"),
              "predictive_code_manifest_sha256":bundle.get("predictive_code_manifest_sha256"),
              "acquisition_code_manifest_sha256":bundle.get("acquisition_code_manifest_sha256"),
              "evaluator_code_git_blob":cfg.get("evaluator_code_git_blob")}

    result,capture=evaluate_cfb_candidate_bakeoff_v3(rows,cfg,input_identity=identity)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    args.private_capture_out.parent.mkdir(parents=True,exist_ok=True)
    args.private_capture_out.write_text(json.dumps(capture,indent=2,sort_keys=True)+"\n")
    os.chmod(args.private_capture_out,0o600)

    print(json.dumps({"status":result["status"],"result_sha256":result["result_sha256"],
                      "winner":result["winner"],"private_capture_sha256":capture["capture_sha256"],
                      "private_capture_retained_family":capture.get("retained_family"),
                      "attempt_budget_consumed_by_evaluation":4,
                      "model_p_created":False,"truth_gate_authority":False,
                      "promotion_authority":False,"eligibility_changed":False,
                      "staking_authority":False,"evidence_clock_authority":False,
                      "official_authority":False},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
