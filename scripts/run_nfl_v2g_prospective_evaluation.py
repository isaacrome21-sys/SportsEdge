#!/usr/bin/env python3
"""Evaluate immutable NFL V2G prospective evidence at fixed checkpoints.

This runner never fetches or writes game-result source data. Canonical outcomes
must already exist in the outcome-capture lane on the durable data branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.sports.nfl.v2g_prospective_evaluation import build_settlement, evaluate_checkpoint, validate_policy


def _read(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def _sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()

def _write_first(path: Path, payload) -> bool:
    text=json.dumps(payload,indent=2,sort_keys=True)+"\n"; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        existing=path.read_text(encoding="utf-8")
        if existing!=text: raise SystemExit(f"NFL_V2G_EVAL_FIRST_WRITE_CONFLICT:{path}")
        return False
    path.write_text(text,encoding="utf-8"); return True


def _verify_clv_source(clv: dict, decision_path: Path) -> None:
    decision_sha=_sha(decision_path)
    if str(clv.get("decision_file_sha256") or "").lower()!=decision_sha:
        raise SystemExit(f"NFL_V2G_EVAL_CLV_DECISION_FILE_SHA_MISMATCH:{decision_path}")
    raw_close=decision_path.parent/"raw_close.json"
    if not raw_close.exists(): raise SystemExit(f"NFL_V2G_EVAL_RAW_CLOSE_MISSING:{raw_close}")
    if str(clv.get("raw_close_file_sha256") or "").lower()!=_sha(raw_close):
        raise SystemExit(f"NFL_V2G_EVAL_RAW_CLOSE_SHA_MISMATCH:{raw_close}")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--policy",type=Path,required=True)
    p.add_argument("--forward-root",type=Path,required=True)
    p.add_argument("--binding-dir",type=Path,required=True)
    p.add_argument("--canonical-outcome-dir",type=Path,required=True)
    p.add_argument("--evaluation-root",type=Path,required=True)
    a=p.parse_args(); now=datetime.now(timezone.utc); policy=_read(a.policy); validate_policy(policy)
    settlements_dir=a.evaluation_root/"settlements"; checkpoints=a.evaluation_root/"checkpoints"
    created=0; outcome_missing=0
    for decision_path in sorted(a.forward_root.glob("week*/*/decision.json")):
        decision=_read(decision_path); game_id=str(decision.get("game_id") or ""); out=settlements_dir/f"{game_id}.json"
        outcome_path=a.canonical_outcome_dir/f"{game_id}.json"
        if not outcome_path.exists(): outcome_missing+=1; continue
        outcome=_read(outcome_path)
        binding_path=a.binding_dir/f"{game_id}.json"; binding=_read(binding_path) if binding_path.exists() else None
        clv_path=decision_path.parent/"clv.json"; clv=_read(clv_path) if clv_path.exists() else None
        if clv is not None: _verify_clv_source(clv,decision_path)
        settlement=build_settlement(decision,binding,clv,outcome,policy=policy)
        settlement["canonical_outcome_path"]=str(outcome_path)
        settlement["canonical_outcome_file_sha256"]=_sha(outcome_path)
        settlement["decision_file_sha256"]=_sha(decision_path)
        settlement["binding_file_sha256"]=_sha(binding_path) if binding_path.exists() else None
        settlement["clv_file_sha256"]=_sha(clv_path) if clv_path.exists() else None
        settlement["evaluation_policy_sha256"]=_sha(a.policy)
        created+=int(_write_first(out,settlement))
    settlements=[_read(path) for path in sorted(settlements_dir.glob("*.json"))] if settlements_dir.exists() else []
    eligible=sum(bool(row.get("eligible_for_checkpoint")) for bundle in settlements for row in bundle.get("rows") or [])
    checkpoint_created=[]
    for count in policy["checkpoints"]["fixed_eligible_bet_counts"]:
        count=int(count); dest=checkpoints/f"checkpoint_{count:04d}.json"
        if dest.exists() or eligible<count: continue
        report=evaluate_checkpoint(settlements,count=count,policy=policy)
        report["evaluation_policy_sha256"]=_sha(a.policy); report["generated_at_utc"]=now.isoformat()
        _write_first(dest,report); checkpoint_created.append(count)
    print(json.dumps({"settlements_created":created,"settlements_total":len(settlements),"eligible_bets":eligible,"checkpoints_created":checkpoint_created,"canonical_outcomes_missing":outcome_missing,"checked_at_utc":now.isoformat()},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
