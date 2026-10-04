"""NFL V2K Attempt-2 validation integration.

Reuses Attempt-1 source parsing/evaluation mechanics while replacing fold fit
with the schedule-bound Attempt-2 fit. This file is development-only until the
Attempt-2 contract freezes exact code identity and seed.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path
from typing import Mapping
from . import v2k_attempt1_validation as a1
from .v2k_drive_core import derive_path_seed
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
    games=sorted((g for g in identity.values() if g["season"]==fold["test_season"]),key=lambda g:g["game_id"])
    mine=[g for i,g in enumerate(games) if i%shard_count==shard_index]
    results=[simulate_game_histograms(model,g,root_seed=root_seed,paths=paths) for g in mine]
    return {"schema":SHARD_SCHEMA,"fold_id":fold["fold_id"],"train_seasons":list(fold["train_seasons"]),
            "test_season":fold["test_season"],"shard_index":shard_index,"shard_count":shard_count,
            "root_seed":root_seed,"paths_per_game":paths,"training_drive_rows":len(train),
            "fold_test_game_count":len(games),"games":results,"sportsbook_prices_consumed":False}

def evaluate(shards,schedule,contract):
    """Attempt-2 engineering readout. Metrics are diagnostics, not authority gates."""
    binding=contract["attempt2_issue_binding"]
    games={}; seen=defaultdict(set)
    for s in shards:
        if s["schema"]!=SHARD_SCHEMA or s["root_seed"]!=binding["root_seed"]:
            raise SystemExit("V2K_SHARD_IDENTITY_INVALID")
        seen[(s["fold_id"],s["shard_count"])].add(s["shard_index"])
        for g in s["games"]:
            if g["game_id"] in games: raise SystemExit("V2K_DUPLICATE_GAME:"+g["game_id"])
            if g["paths"]!=s["paths_per_game"]: raise SystemExit("V2K_PATH_COUNT_INCONSISTENT")
            games[g["game_id"]]=g
    for (fold_id,count),idx in seen.items():
        if idx!=set(range(count)): raise SystemExit(f"V2K_SHARDS_INCOMPLETE:{fold_id}")
    expected={g for g,r in schedule.items() if 2021<=r["season"]<=2025}
    if set(games)!=expected:
        raise SystemExit(f"V2K_EVALUATED_GAME_SET_MISMATCH:missing={len(expected-set(games))}:extra={len(set(games)-expected)}")
    if {f["fold_id"] for f in binding["fold_plan"]["folds"]}!={k[0] for k in seen}:
        raise SystemExit("V2K_FOLD_SET_MISMATCH")

    rows=[]; key_sum={k:0.0 for k in a1.KEYS}
    for gid in sorted(games):
        g,sched=games[gid],schedule[gid]
        if (g["home_team"],g["away_team"])!=(sched["home_team"],sched["away_team"]):
            raise SystemExit("V2K_HOME_AWAY_DRIFT:"+gid)
        mh,th=a1._hist(g["margin_hist"]),a1._hist(g["total_hist"])
        n=sum(count for _,count in mh)
        for k in a1.KEYS: key_sum[k]+=sum(count for value,count in mh if value==k)/n
        m=sched["_market"]; margin=sched["home_score"]-sched["away_score"]; total=sched["home_score"]+sched["away_score"]
        sl,tl=m["spread_line"],m["total_line"]
        rows.append({
            "game_id":gid,"season":sched["season"],"week":sched["week"],
            "home_score":sched["home_score"],"away_score":sched["away_score"],
            "spread_line":sl,"total_line":tl,
            "home_cover_outcome":None if sl is None or margin==sl else int(margin>sl),
            "over_outcome":None if tl is None or total==tl else int(total>tl),
            "baseline_home_cover_prob":a1._novig(m["home_spread_odds"],m["away_spread_odds"]),
            "baseline_over_prob":a1._novig(m["over_odds"],m["under_odds"]),
            "candidate_home_cover_prob":a1._over_prob(mh,sl),
            "candidate_over_prob":a1._over_prob(th,tl),
            "candidate_home_win_prob":a1._over_prob(mh,0.0),
            "sim_mean_margin":sum(v*count for v,count in mh)/n,
            "sim_mean_total":sum(v*count for v,count in th)/n,
        })

    folds=[]; predictive={}
    specs={"spread":("home_cover_outcome","baseline_home_cover_prob","candidate_home_cover_prob"),
           "total":("over_outcome","baseline_over_prob","candidate_over_prob")}
    for market,(outcome_key,base_key,cand_key) in specs.items():
        wins=total_folds=0
        for season in sorted({r["season"] for r in rows}):
            comp=[r for r in rows if r["season"]==season and r[outcome_key] in (0,1)
                  and r[base_key] is not None and r[cand_key] is not None]
            if not comp: continue
            bll=a1._log_loss([(r[outcome_key],r[base_key]) for r in comp])
            cll=a1._log_loss([(r[outcome_key],r[cand_key]) for r in comp])
            beat=cll<bll; wins+=int(beat); total_folds+=1
            folds.append({"season":season,"market":market,"n":len(comp),"baseline_log_loss":bll,
                          "candidate_log_loss":cll,"candidate_beats_baseline":beat})
        predictive[market]={"fold_wins":wins,"fold_total":total_folds,
                            "fold_win_rate":wins/total_folds if total_folds else None}

    n_games=len(games)
    key_prob={str(k):key_sum[k]/n_games for k in a1.KEYS}
    reference=a1._load_json(REFERENCE_PATH)["reference"]["signed_margin_mass"]
    key_err={str(k):abs(key_prob[str(k)]-float(reference[str(k)])) for k in a1.KEYS}
    key_rmse=sqrt(sum(e*e for e in key_err.values())/len(a1.KEYS))
    return {
        "schema":RESULT_SCHEMA,"candidate_family":contract["candidate_family"],
        "evaluation_status":"ATTEMPT2_READOUT_COMPLETE","diagnostics_only":True,
        "predictive_diagnostics":predictive,"folds":folds,
        "structural_diagnostics":{"candidate_signed_key_probability":key_prob,
            "reference_signed_key_probability":{str(k):float(reference[str(k)]) for k in a1.KEYS},
            "abs_error_by_key":key_err,"candidate_signed_key_mass_rmse":key_rmse},
        "evaluated_game_count":n_games,"game_rows":rows,
        "sportsbook_prices_consumed_in_fit":False,"sportsbook_prices_consumed_in_evaluation_only":True,
        "authority":{"pricing":False,"staking":False,"production_release":False,"untouched_readout":False},
    }
