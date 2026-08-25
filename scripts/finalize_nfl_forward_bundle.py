#!/usr/bin/env python3
"""Finalize one scheduled NFL forward capture into the v2 attestation bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT=re.compile(r"^[0-9a-f]{40}$")
_CONTRACT="NFL_FORWARD_CLV_COLLECTION_V2"


def _sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _git(value:str,error:str)->str:
    raw=str(value or "").strip().lower()
    if not _GIT.fullmatch(raw): raise SystemExit(error)
    return raw

def _jsonl(path:Path)->list[dict]:
    rows=[]
    for i,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        try: row=json.loads(line)
        except json.JSONDecodeError as exc: raise SystemExit(f"NFL_FORWARD_FINALIZE_JSONL_INVALID:{path}:{i}") from exc
        if not isinstance(row,dict): raise SystemExit(f"NFL_FORWARD_FINALIZE_ROW_INVALID:{path}:{i}")
        rows.append(row)
    if not rows: raise SystemExit(f"NFL_FORWARD_FINALIZE_EMPTY:{path}")
    return rows


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--decisions",type=Path,required=True); p.add_argument("--closes",type=Path,required=True)
    p.add_argument("--model-artifact",type=Path,required=True); p.add_argument("--collector-git-sha",required=True); p.add_argument("--model-code-git-sha",required=True)
    p.add_argument("--out-dir",type=Path,default=Path("artifacts/football/forward")); a=p.parse_args()
    collector=_git(a.collector_git_sha,"NFL_FORWARD_FINALIZE_COLLECTOR_SHA_INVALID"); model_sha=_git(a.model_code_git_sha,"NFL_FORWARD_FINALIZE_MODEL_SHA_INVALID")
    model_hash=_sha(a.model_artifact)
    decisions=_jsonl(a.decisions); closes=_jsonl(a.closes)
    for i,row in enumerate(decisions,1):
        if str(row.get("code_git_sha") or "").lower()!=model_sha: raise SystemExit(f"NFL_FORWARD_FINALIZE_DECISION_CODE_SHA_MISMATCH:{i}")
        if str(row.get("model_artifact_sha256") or "").lower()!=model_hash: raise SystemExit(f"NFL_FORWARD_FINALIZE_MODEL_ARTIFACT_MISMATCH:{i}")
        if row.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or row.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise SystemExit(f"NFL_FORWARD_FINALIZE_DECISION_MODEL_IDENTITY_MISMATCH:{i}")
    for i,row in enumerate(closes,1):
        if str(row.get("code_git_sha") or "").lower()!=model_sha: raise SystemExit(f"NFL_FORWARD_FINALIZE_CLOSE_CODE_SHA_MISMATCH:{i}")
        if row.get("model_id")!=PRODUCTION_NFL_M2_MODEL_ID or row.get("feature_contract")!=NFL_M2_FEATURE_CONTRACT: raise SystemExit(f"NFL_FORWARD_FINALIZE_CLOSE_MODEL_IDENTITY_MISMATCH:{i}")

    a.out_dir.mkdir(parents=True,exist_ok=True)
    d=a.out_dir/"nfl_forward_decisions.jsonl"; c=a.out_dir/"nfl_forward_closes.jsonl"; m=a.out_dir/"nfl_m2_model.json"; e=a.out_dir/"nfl_clv_evidence.json"
    shutil.copyfile(a.decisions,d); shutil.copyfile(a.closes,c); shutil.copyfile(a.model_artifact,m)
    subprocess.run([sys.executable,"scripts/build_nfl_clv_evidence.py","--decisions",str(d),"--closes",str(c),"--git-sha",model_sha,"--out",str(e)],check=True)
    evidence=json.loads(e.read_text(encoding="utf-8")); evidence["model_artifact_sha256"]=model_hash
    if evidence.get("promotion_decision_contract")!="SHADOW_QUALIFIED_OR_OFFICIAL": raise SystemExit("NFL_FORWARD_FINALIZE_PROMOTION_DECISION_CONTRACT_INVALID")
    e.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    artifacts=[d,c,e,m]
    manifest={"schema_version":2,"collector_contract":_CONTRACT,"collector_git_sha":collector,"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash,"model_id":PRODUCTION_NFL_M2_MODEL_ID,"feature_contract":NFL_M2_FEATURE_CONTRACT,"artifacts":[{"path":x.name,"sha256":_sha(x)} for x in artifacts]}
    (a.out_dir/"nfl_forward_clv_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"collector_git_sha":collector,"model_code_git_sha":model_sha,"model_artifact_sha256":model_hash,"decision_count":evidence["decision_count"],"close_count":evidence["close_count"]},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
