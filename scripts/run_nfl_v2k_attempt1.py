#!/usr/bin/env python3
"""NFL V2K Attempt-1 development/validation runner.

Two stages so the 50,000-path simulation can be sharded across CI jobs:

  simulate  fit one pre-registered fold on its training seasons (market-blind
            nflverse drives) and write per-game margin/total histograms for a
            deterministic shard of the fold's test games.
  evaluate  join every shard with the official schedule, read market lines for
            evaluation only, and apply the frozen structural + predictive gates.

Fold plan, root seed and path count are read from the frozen preattempt
contract, never re-declared here. ``--smoke`` runs below the 10,000-path floor
and is stamped NOT_AN_ATTEMPT; a non-smoke ``evaluate`` output consumes
Attempt 1 and must be recorded in NFL_V2K_ATTEMPT_LEDGER_V1.json by a
follow-up PR.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.sports.nfl import v2k_attempt1_validation as v  # noqa: E402


def _fold(contract: dict, fold_id: str) -> dict:
    for f in contract["attempt1_issue_binding"]["fold_plan"]["folds"]:
        if f["fold_id"] == fold_id:
            return f
    raise SystemExit("V2K_UNKNOWN_FOLD:" + fold_id)


def cmd_simulate(a) -> None:
    contract = v.preflight(paths=a.paths, smoke=a.smoke)
    sources = v.verify_sources(a.pbp_dir, a.schedule, contract)
    identity = v.schedule_identity(v.load_schedule(a.schedule))
    fold = _fold(contract, a.fold)
    manifest = contract["source_binding"]["source_manifest_sha256"]
    seasons = sorted(set(fold["train_seasons"]) | {fold["test_season"]})
    drives = {y: v.build_season_drives(a.pbp_dir / f"play_by_play_{y}.csv.gz", identity, season=y,
                                       source_manifest_sha=manifest, code_sha=a.code_sha) for y in seasons}
    shard = v.run_fold_shard(fold=fold, drives_by_season=drives, identity=identity,
                             root_seed=int(contract["attempt1_issue_binding"]["root_seed"]), paths=a.paths,
                             shard_index=a.shard_index, shard_count=a.shard_count, workers=a.workers)
    shard.update({"code_sha": a.code_sha, "smoke": a.smoke, "source_attestation": sources,
                  "drive_rows_by_season": {str(y): len(r) for y, r in drives.items()}})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(shard, sort_keys=True) + "\n")


def cmd_evaluate(a) -> None:
    files = sorted(a.shards_dir.rglob("*.json"))
    shards = [json.loads(f.read_text()) for f in files]
    if not shards:
        raise SystemExit("V2K_NO_SHARDS")
    smoke = {s.get("smoke") for s in shards}
    paths = {s["paths_per_game"] for s in shards}
    codes = {s.get("code_sha") for s in shards}
    if len(smoke) != 1 or len(paths) != 1 or len(codes) != 1:
        raise SystemExit("V2K_SHARDS_MIXED_RUNS")
    is_smoke = smoke.pop()
    contract = v.preflight(paths=paths.pop(), smoke=is_smoke)
    v.verify_sources(a.pbp_dir, a.schedule, contract)
    result = v.evaluate(shards, v.load_schedule(a.schedule), contract)
    result.update({"code_sha": codes.pop(), "smoke": is_smoke,
                   "run_status": "NOT_AN_ATTEMPT_SMOKE" if is_smoke else "ATTEMPT1_CONSUMED",
                   "attempt_consumed": not is_smoke,
                   "root_seed": contract["attempt1_issue_binding"]["root_seed"],
                   "paths_per_game": shards[0]["paths_per_game"]})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    s, p = result["structural_gate"], result["predictive_gate"]
    print(json.dumps({"verdict": result["verdict"], "run_status": result["run_status"],
                      "structural_pass": s["pass"], "key_rmse": s["candidate_signed_key_mass_rmse"],
                      "slope_metric": s["candidate_calibration_slope_metric"],
                      "spread": p["spread"], "total": p["total"]}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate")
    s.add_argument("--fold", required=True)
    s.add_argument("--shard-index", type=int, default=0)
    s.add_argument("--shard-count", type=int, default=1)
    s.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    s.add_argument("--code-sha", required=True)
    s.add_argument("--paths", type=int, required=True)
    s.add_argument("--smoke", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("--shards-dir", type=Path, required=True)
    for p in (s, e):
        p.add_argument("--pbp-dir", type=Path, required=True)
        p.add_argument("--schedule", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "simulate":
        if not 0 <= a.shard_index < a.shard_count:
            raise SystemExit("V2K_SHARD_ARGS_INVALID")
        cmd_simulate(a)
    else:
        cmd_evaluate(a)


if __name__ == "__main__":
    main()
