#!/usr/bin/env python3
"""Build the final NFL registry from independent CI and scheduled CLV bundles.

The scheduled collector may run from a newer ``main`` head than the pinned NFL
model release. Authenticity therefore binds two identities separately:
- collector workflow head: proves which scheduled code captured the bytes;
- model code SHA + fitted model hash: must match the successful production-M2
  evidence bundle exactly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sportsedge.core.promotion.nfl_external_deployment import build_externally_attested_nfl_registry
from sportsedge.core.validation.nfl_ci_attestation import verify_nfl_pre_ci_bundle
from sportsedge.core.validation.nfl_forward_clv_attestation import verify_nfl_forward_clv_bundle


def _json(path:Path)->dict[str,Any]:
    try: p=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise ValueError(f"NFL_EXTERNAL_ATTESTATION_JSON_INVALID:{path}") from exc
    if not isinstance(p,dict): raise ValueError(f"NFL_EXTERNAL_ATTESTATION_JSON_NOT_OBJECT:{path}")
    return p


def _markets(path:Path)->list[str]:
    p=_json(path)
    if "NFL" not in {str(x).upper() for x in p.get("sports",[])}: raise ValueError("NFL_MARKET_SURFACE_NOT_DECLARED")
    out=[]
    for row in p.get("markets",[]):
        m=str(row.get("market") or "").strip().lower() if isinstance(row,dict) else ""
        if m and m not in out: out.append(m)
    if not out: raise ValueError("NFL_MARKET_SURFACE_EMPTY")
    return out


def build_registry_from_bundles(*,ci_bundle_dir:Path,ci_workflow_name:str,ci_workflow_conclusion:str,ci_workflow_head_sha:str,ci_workflow_run_id:int,forward_bundle_dir:Path,forward_workflow_name:str,forward_workflow_conclusion:str,forward_workflow_event:str,forward_workflow_head_branch:str,forward_workflow_head_sha:str,forward_workflow_run_id:int,market_surface:Path)->dict[str,Any]:
    ci=verify_nfl_pre_ci_bundle(ci_bundle_dir,workflow_name=ci_workflow_name,workflow_conclusion=ci_workflow_conclusion,workflow_head_sha=ci_workflow_head_sha,workflow_run_id=ci_workflow_run_id)
    clv_att=verify_nfl_forward_clv_bundle(forward_bundle_dir,workflow_name=forward_workflow_name,workflow_conclusion=forward_workflow_conclusion,workflow_event=forward_workflow_event,workflow_head_branch=forward_workflow_head_branch,workflow_head_sha=forward_workflow_head_sha,workflow_run_id=forward_workflow_run_id)
    if ci["git_sha"]!=clv_att["git_sha"]: raise ValueError("NFL_EXTERNAL_ATTESTATION_CODE_SHA_MISMATCH")
    if ci.get("model_artifact_sha256")!=clv_att.get("model_artifact_sha256"): raise ValueError("NFL_EXTERNAL_ATTESTATION_MODEL_ARTIFACT_MISMATCH")
    math_p=_json(ci_bundle_dir/"nfl_simulator_profile.json"); math=math_p.get("math_artifact",math_p)
    if not isinstance(math,dict): raise ValueError("NFL_EXTERNAL_ATTESTATION_MATH_ARTIFACT_INVALID")
    history=_json(ci_bundle_dir/"nfl_production_validation.json"); clv=_json(forward_bundle_dir/"nfl_clv_evidence.json")
    return build_externally_attested_nfl_registry(math,history,declared_markets=_markets(market_surface),ci_attestation=ci,clv_evidence=clv,clv_attestation=clv_att)


def main()->int:
    p=argparse.ArgumentParser()
    for name in ("ci-bundle-dir","forward-bundle-dir"): p.add_argument("--"+name,type=Path,required=True)
    for name in ("ci-workflow-name","ci-workflow-conclusion","ci-workflow-head-sha","forward-workflow-name","forward-workflow-conclusion","forward-workflow-event","forward-workflow-head-branch","forward-workflow-head-sha"): p.add_argument("--"+name,required=True)
    p.add_argument("--ci-workflow-run-id",type=int,required=True); p.add_argument("--forward-workflow-run-id",type=int,required=True)
    p.add_argument("--market-surface",type=Path,default=Path("config/football_market_surface.json")); p.add_argument("--out",type=Path,default=Path("artifacts/football/nfl_externally_attested_registry.json")); a=p.parse_args()
    r=build_registry_from_bundles(ci_bundle_dir=a.ci_bundle_dir,ci_workflow_name=a.ci_workflow_name,ci_workflow_conclusion=a.ci_workflow_conclusion,ci_workflow_head_sha=a.ci_workflow_head_sha,ci_workflow_run_id=a.ci_workflow_run_id,forward_bundle_dir=a.forward_bundle_dir,forward_workflow_name=a.forward_workflow_name,forward_workflow_conclusion=a.forward_workflow_conclusion,forward_workflow_event=a.forward_workflow_event,forward_workflow_head_branch=a.forward_workflow_head_branch,forward_workflow_head_sha=a.forward_workflow_head_sha,forward_workflow_run_id=a.forward_workflow_run_id,market_surface=a.market_surface)
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"code_git_sha":r["code_git_sha"],"collector_git_sha":r["clv_attestation"]["collector_git_sha"],"deployed_markets":r["deployed_markets"],"ci_workflow_run_id":r["ci_attestation"]["workflow_run_id"],"forward_clv_workflow_run_id":r["clv_attestation"]["workflow_run_id"],"clv_attestation_state":r["clv_attestation_state"]},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
