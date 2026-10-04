#!/usr/bin/env python3
"""NFL V2K Attempt-2 development/validation runner.

Phase-2 execution surface. It deliberately refuses to run until the Attempt-2
contract and validation/core implementation are present and frozen. Smoke runs
below the frozen simulation floor remain NOT_AN_ATTEMPT.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from sportsedge.sports.nfl import v2k_attempt2_validation as v
except ImportError as exc:
    raise SystemExit("V2K_ATTEMPT2_IMPLEMENTATION_NOT_PRESENT") from exc

def _binding(contract):
    b=contract.get("attempt2_issue_binding")
    if not isinstance(b,dict): raise SystemExit("V2K_ATTEMPT2_BINDING_NOT_FROZEN")
    return b

def _fold(contract, fold_id):
    for f in _binding(contract)["fold_plan"]["folds"]:
        if f["fold_id"]==fold_id: return f
    raise SystemExit("V2K_UNKNOWN_FOLD:"+fold_id)

def _source_verifier_contract(contract):
    """Adapt the frozen source manifest to the legacy verifier without changing model identity."""
    binding=dict(contract.get("source_binding") or {})
    freeze_path=binding.get("source_freeze_path")
    seasons=binding.get("pbp_seasons")
    if not freeze_path or not isinstance(seasons,list) or not seasons:
        raise SystemExit("V2K_SOURCE_BINDING_INCOMPLETE")
    freeze=json.loads((v.ROOT / freeze_path).read_text(encoding="utf-8"))
    expected=((freeze.get("seasonal_sources") or {}).get("pbp") or {}).get("expected_sha256_by_season") or {}
    selected={}
    for season in seasons:
        sha=expected.get(str(season))
        if not sha:
            raise SystemExit(f"V2K_SOURCE_FREEZE_PBP_SHA_MISSING:{season}")
        selected[str(season)]=sha
    adapted=dict(contract)
    adapted["source_binding"]={**binding,"pbp_sha256_by_season":selected}
    return adapted

def _verify_frozen_sources(pbp_dir, schedule, contract):
    return v.verify_sources(pbp_dir,schedule,_source_verifier_contract(contract))

def cmd_simulate(a):
    pf=v.preflight(paths=a.paths, smoke=a.smoke); contract=pf["contract"]
    sources=_verify_frozen_sources(a.pbp_dir,a.schedule,contract)
    identity=v.schedule_identity(v.load_schedule(a.schedule))
    fold=_fold(contract,a.fold); manifest=contract["source_binding"]["source_manifest_sha256"]
    seasons=sorted(set(fold["train_seasons"])|{fold["test_season"]})
    drives={y:v.build_season_drives(a.pbp_dir/f"play_by_play_{y}.csv.gz",identity,season=y,source_manifest_sha=manifest,code_sha=a.code_sha) for y in seasons}
    shard=v.run_fold_shard(fold=fold,drives_by_season=drives,identity=identity,root_seed=int(_binding(contract)["root_seed"]),paths=a.paths,shard_index=a.shard_index,shard_count=a.shard_count,workers=a.workers)
    shard.update({"code_sha":a.code_sha,"smoke":a.smoke,"source_attestation":sources})
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(shard,sort_keys=True)+"\n")

def cmd_evaluate(a):
    shards=[json.loads(f.read_text()) for f in sorted(a.shards_dir.rglob("*.json"))]
    if not shards: raise SystemExit("V2K_NO_SHARDS")
    smoke={s.get("smoke") for s in shards}; paths={s["paths_per_game"] for s in shards}; codes={s.get("code_sha") for s in shards}
    if len(smoke)!=1 or len(paths)!=1 or len(codes)!=1: raise SystemExit("V2K_SHARDS_MIXED_RUNS")
    is_smoke=smoke.pop(); pf=v.preflight(paths=paths.pop(),smoke=is_smoke); contract=pf["contract"]
    _verify_frozen_sources(a.pbp_dir,a.schedule,contract)
    result=v.evaluate(shards,v.load_schedule(a.schedule),contract)
    result.update({"code_sha":codes.pop(),"smoke":is_smoke,"run_status":"NOT_AN_ATTEMPT_SMOKE" if is_smoke else "ATTEMPT2_CONSUMED","attempt_consumed":not is_smoke,"root_seed":_binding(contract)["root_seed"],"paths_per_game":shards[0]["paths_per_game"]})
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd",required=True)
    s=sub.add_parser("simulate"); s.add_argument("--fold",required=True); s.add_argument("--shard-index",type=int,default=0); s.add_argument("--shard-count",type=int,default=1); s.add_argument("--workers",type=int,default=os.cpu_count() or 1); s.add_argument("--code-sha",required=True); s.add_argument("--paths",type=int,required=True); s.add_argument("--smoke",action="store_true")
    e=sub.add_parser("evaluate"); e.add_argument("--shards-dir",type=Path,required=True)
    for p in (s,e): p.add_argument("--pbp-dir",type=Path,required=True); p.add_argument("--schedule",type=Path,required=True); p.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    if a.cmd=="simulate":
        if not 0<=a.shard_index<a.shard_count: raise SystemExit("V2K_SHARD_ARGS_INVALID")
        cmd_simulate(a)
    else: cmd_evaluate(a)
if __name__=="__main__": main()
