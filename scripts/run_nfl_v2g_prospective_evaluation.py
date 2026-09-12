#!/usr/bin/env python3
"""Archive final NFL outcomes and emit immutable V2G fixed-checkpoint reports."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.sports.nfl.v2g_prospective_evaluation import build_settlement, evaluate_checkpoint, validate_policy


def _read(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def _sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()

def _write_first(path: Path, payload) -> bool:
    text=json.dumps(payload,indent=2,sort_keys=True)+"\n"; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): return False
    path.write_text(text,encoding="utf-8"); return True


def _schedule(path: Path) -> dict[str,dict]:
    with path.open(newline="",encoding="utf-8-sig") as handle:
        rows={}
        for row in csv.DictReader(handle):
            if str(row.get("season") or "")!="2026": continue
            game_id=str(row.get("game_id") or "").strip()
            if game_id: rows[game_id]=row
        return rows


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--schedule",type=Path,required=True); p.add_argument("--policy",type=Path,required=True)
    p.add_argument("--forward-root",type=Path,required=True); p.add_argument("--binding-dir",type=Path,required=True)
    p.add_argument("--outcome-root",type=Path,required=True)
    a=p.parse_args(); now=datetime.now(timezone.utc); policy=_read(a.policy); validate_policy(policy)
    schedule_sha=_sha(a.schedule); games=_schedule(a.schedule)
    settlements_dir=a.outcome_root/"settlements"/"2026"; snapshots=a.outcome_root/"schedule_snapshots"; checkpoints=a.outcome_root/"checkpoints"
    created=0; skipped_not_final=0
    for decision_path in sorted(a.forward_root.glob("week*/*/decision.json")):
        decision=_read(decision_path); game_id=str(decision.get("game_id") or ""); out=settlements_dir/f"{game_id}.json"
        if out.exists(): continue
        outcome=games.get(game_id)
        if outcome is None: continue
        binding_path=a.binding_dir/f"{game_id}.json"; binding=_read(binding_path) if binding_path.exists() else None
        clv_path=decision_path.parent/"clv.json"; clv=_read(clv_path) if clv_path.exists() else None
        try:
            settlement=build_settlement(decision,binding,clv,outcome,outcome_snapshot_sha256=schedule_sha,observed_at=now,policy=policy)
        except ValueError as exc:
            text=str(exc)
            if text in {"NFL_V2G_EVAL_OUTCOME_TOO_EARLY","NFL_V2G_EVAL_HOME_SCORE_MISSING","NFL_V2G_EVAL_AWAY_SCORE_MISSING"}:
                skipped_not_final+=1; continue
            raise
        created+=int(_write_first(out,settlement))
    if created:
        snapshots.mkdir(parents=True,exist_ok=True); snap=snapshots/f"{schedule_sha}.csv"
        if snap.exists():
            if _sha(snap)!=schedule_sha: raise SystemExit("NFL_V2G_EVAL_SCHEDULE_SNAPSHOT_HASH_MISMATCH")
        else: shutil.copyfile(a.schedule,snap)
    settlements=[_read(path) for path in sorted(settlements_dir.glob("*.json"))] if settlements_dir.exists() else []
    eligible=sum(bool(row.get("eligible_for_checkpoint")) for bundle in settlements for row in bundle.get("rows") or [])
    checkpoint_created=[]
    for count in policy["checkpoints"]["fixed_eligible_bet_counts"]:
        count=int(count); dest=checkpoints/f"checkpoint_{count:04d}.json"
        if dest.exists() or eligible<count: continue
        report=evaluate_checkpoint(settlements,count=count,policy=policy)
        report["evaluation_policy_sha256"]=_sha(a.policy); report["generated_at_utc"]=now.isoformat()
        _write_first(dest,report); checkpoint_created.append(count)
    print(json.dumps({"settlements_created":created,"settlements_total":len(settlements),"eligible_bets":eligible,"checkpoints_created":checkpoint_created,"not_final_or_too_early":skipped_not_final,"schedule_sha256":schedule_sha,"checked_at_utc":now.isoformat()},sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
