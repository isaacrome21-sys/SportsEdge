"""NFL V2K Attempt-2 validation integration.

Reuses Attempt-1 source parsing/evaluation mechanics while replacing fold fit
with the schedule-bound Attempt-2 fit. This file is development-only until the
Attempt-2 contract freezes exact code identity and seed.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Mapping
from . import v2k_attempt1_validation as a1
from .v2k_drive_core import derive_path_seed, simulate_joint_game
from .v2k_drive_core_v2 import fit_attempt2, simulate_joint_game_v2

NFL=Path(__file__).resolve().parent
ROOT=NFL.parents[2]
CONTRACT_PATH=NFL/"NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V2.json"
LEDGER_PATH=NFL/"NFL_V2K_ATTEMPT_LEDGER_V1.json"
REFERENCE_PATH=a1.REFERENCE_PATH
SHARD_SCHEMA="NFL_V2K_ATTEMPT2_SHARD_V1"
RESULT_SCHEMA="NFL_V2K_ATTEMPT2_DEVELOPMENT_VALIDATION_V1"

sha256_file=a1.sha256_file
git_blob_sha1=a1.git_blob_sha1
read_csv=a1.read_csv
verify_sources=a1.verify_sources
load_schedule=a1.load_schedule
schedule_identity=a1.schedule_identity
pbp_game_drive_records=a1.pbp_game_drive_records
build_season_drives=a1.build_season_drives

def preflight(*,paths:int,smoke:bool)->dict:
    contract=a1._load_json(CONTRACT_PATH); ledger=a1._load_json(LEDGER_PATH)
    problems=[]
    if contract.get("status")!="DEVELOPMENT_NOT_FROZEN":
        problems.append("V2K_ATTEMPT2_UNEXPECTED_STATUS")
    # Phase 2 is intentionally non-executable until freeze.
    problems.append("V2K_ATTEMPT2_CODE_IDENTITY_NOT_FROZEN")
    raise SystemExit("PREFLIGHT_FAILED:"+";".join(problems))

def simulate_game_histograms(model,game:Mapping,*,root_seed:int,paths:int)->dict:
    margins=Counter(); totals=Counter()
    for idx in range(paths):
        seed=derive_path_seed(root_seed=root_seed,game_key=game["game_id"],path_index=idx)
        s=simulate_joint_game_v2(model,game["home_team"],game["away_team"],season=game["season"],seed=seed)
        margins[s.margin]+=1; totals[s.total]+=1
    return {"game_id":game["game_id"],"season":game["season"],"week":game["week"],
            "home_team":game["home_team"],"away_team":game["away_team"],"paths":paths,
            "margin_hist":{str(k):v for k,v in sorted(margins.items())},
            "total_hist":{str(k):v for k,v in sorted(totals.items())}}
def run_fold_shard(*,fold,drives_by_season,identity,root_seed,paths,shard_index,shard_count,workers):
    train=[r for y in fold["train_seasons"] for r in drives_by_season[y]]
    train_ids={g:m for g,m in identity.items() if m["season"] in fold["train_seasons"]}
    model=fit_attempt2(train,train_ids)
    raise SystemExit("V2K_ATTEMPT2_SIMULATION_MECHANICS_NOT_IMPLEMENTED")

def evaluate(shards,schedule,contract):
    raise SystemExit("V2K_ATTEMPT2_EVALUATION_NOT_FROZEN")
