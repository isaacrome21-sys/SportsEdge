"""NFL V2K Attempt-3 development/validation integration.

Implements the preregistered G3 context-skeleton/log-ratio candidate. Market
fields enter only in evaluate(); fit and simulation receive schedule identity
without market prices. Scored execution remains fail-closed until exact code
identities are frozen in the Attempt-3 contract.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Mapping

from sportsedge.core.validation.calibration_truth_gate import evaluate_calibration_truth_gate
from .historical_validation import build_calibration_evidence, calibrate_nfl_evaluations
from . import v2k_attempt1_validation as a1
from .v2k_drive_core import derive_path_seed
from .v2k_drive_core_v3 import fit_attempt3, simulate_joint_game_v3

NFL=Path(__file__).resolve().parent
ROOT=NFL.parents[2]
CONTRACT_PATH=NFL/"NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V3.json"
EXPOSURE_PATH=NFL/"NFL_V2K_DEVELOPMENT_EXPOSURE_V2.json"
REFERENCE_PATH=a1.REFERENCE_PATH
SHARD_SCHEMA="NFL_V2K_ATTEMPT3_SHARD_V1"
RESULT_SCHEMA="NFL_V2K_ATTEMPT3_DEVELOPMENT_VALIDATION_V1"

sha256_file=a1.sha256_file
git_blob_sha1=a1.git_blob_sha1
read_csv=a1.read_csv
verify_sources=a1.verify_sources
load_schedule=a1.load_schedule
schedule_identity=a1.schedule_identity
pbp_game_drive_records=a1.pbp_game_drive_records
build_season_drives=a1.build_season_drives

MIN_CALIBRATION_FIT_SEASONS=a1.MIN_CALIBRATION_FIT_SEASONS
CALIBRATION_BINS=a1.CALIBRATION_BINS
CALIBRATION_MIN_BIN_N=a1.CALIBRATION_MIN_BIN_N
KEYS=a1.KEYS

def _load_json(path:Path)->dict:
    return a1._load_json(path)

def preflight(*,paths:int,smoke:bool)->dict:
    contract=_load_json(CONTRACT_PATH)
    exposure=_load_json(EXPOSURE_PATH)
    problems=[]
    if contract.get("status")!="FROZEN_ATTEMPT3_READY_FOR_DEVELOPMENT_VALIDATION":
        problems.append("V2K_ATTEMPT3_NOT_FROZEN_READY")
    budget=contract.get("attempt_budget") or {}
    if not budget.get("attempt3_scoring_allowed"):
        problems.append("V2K_ATTEMPT3_SCORING_NOT_ALLOWED")
    if exposure.get("development_budget_units_used")!=2:
        problems.append("V2K_ATTEMPT3_EXPOSURE_COUNT_INVALID")
    if exposure.get("development_budget_units_remaining")!=3:
        problems.append("V2K_ATTEMPT3_REMAINING_BUDGET_INVALID")
    if any(bool(v) for v in (exposure.get("authority") or {}).values()):
        problems.append("V2K_ATTEMPT3_EXPOSURE_AUTHORITY_ESCALATION")
    sim=contract.get("simulation") or {}
    root_seed=sim.get("root_seed")
    try:
        root_seed=int(root_seed)
    except (TypeError,ValueError):
        problems.append("V2K_ATTEMPT3_ROOT_SEED_INVALID")
        root_seed=None
    floor=int(sim.get("absolute_floor",10000))
    frozen_paths=int(sim.get("paths_per_game",50000))
    if smoke:
        if paths<1 or paths>=floor:
            problems.append("V2K_ATTEMPT3_SMOKE_PATH_COUNT_INVALID")
    elif paths!=frozen_paths:
        problems.append(f"V2K_ATTEMPT3_PATH_COUNT_NOT_FROZEN:{paths}!={frozen_paths}")
    ident=contract.get("implementation_identity") or {}
    if ident.get("status")!="FROZEN":
        problems.append("V2K_ATTEMPT3_CODE_IDENTITY_NOT_FROZEN")
    for path_key,sha_key in (
        ("core_path","core_git_blob_sha1"),
        ("validation_path","validation_git_blob_sha1"),
        ("runner_path","runner_git_blob_sha1"),
    ):
        rel=ident.get(path_key)
        want=ident.get(sha_key)
        if not rel or not want:
            problems.append("V2K_ATTEMPT3_IMPLEMENTATION_IDENTITY_INCOMPLETE")
        elif git_blob_sha1(ROOT/rel)!=want:
            problems.append("V2K_ATTEMPT3_CODE_IDENTITY_DRIFT:"+rel)
    if problems:
        raise SystemExit("PREFLIGHT_FAILED:"+";".join(problems))
    return {"contract":contract,"root_seed":root_seed,"paths":paths,"smoke":smoke}

def simulate_game_histograms(model,game:Mapping,*,root_seed:int,paths:int)->dict:
    margins=Counter(); totals=Counter(); scores=Counter()
    for idx in range(paths):
        seed=derive_path_seed(root_seed=root_seed,game_key=game["game_id"],path_index=idx)
        s=simulate_joint_game_v3(model,game["home_team"],game["away_team"],season=game["season"],seed=seed)
        margins[s.margin]+=1
        totals[s.total]+=1
        scores[(s.home_score,s.away_score)]+=1
    return {
        "game_id":game["game_id"],"season":game["season"],"week":game["week"],
        "home_team":game["home_team"],"away_team":game["away_team"],"paths":paths,
        "score_hist":{f"{h},{a}":count for (h,a),count in sorted(scores.items())},
        "margin_hist":{str(k):v for k,v in sorted(margins.items())},
        "total_hist":{str(k):v for k,v in sorted(totals.items())},
    }

def run_fold_shard(*,fold,drives_by_season,identity,root_seed,paths,shard_index,shard_count,workers):
    train=[r for y in fold["train_seasons"] for r in drives_by_season[y]]
    train_ids={gid:meta for gid,meta in identity.items() if meta["season"] in set(fold["train_seasons"])}
    model=fit_attempt3(train,train_ids)
    games=sorted((g for g in identity.values() if g["season"]==fold["test_season"]),key=lambda g:g["game_id"])
    mine=[g for i,g in enumerate(games) if i%shard_count==shard_index]
    if workers is None or workers<1:
        raise ValueError("V2K_WORKERS_INVALID")
    if workers==1 or len(mine)<2:
        results=[simulate_game_histograms(model,g,root_seed=root_seed,paths=paths) for g in mine]
    else:
        with ProcessPoolExecutor(max_workers=min(workers,len(mine))) as pool:
            futures=[pool.submit(simulate_game_histograms,model,g,root_seed=root_seed,paths=paths) for g in mine]
            results=[f.result() for f in futures]
    return {
        "schema":SHARD_SCHEMA,"fold_id":fold["fold_id"],"train_seasons":list(fold["train_seasons"]),
        "test_season":fold["test_season"],"shard_index":shard_index,"shard_count":shard_count,
        "root_seed":root_seed,"paths_per_game":paths,"training_drive_rows":len(train),
        "fold_test_game_count":len(games),"games":results,"sportsbook_prices_consumed":False,
    }

def _score_pairs(score_hist:Mapping)->Counter:
    pairs=Counter()
    for key,count in score_hist.items():
        try:
            home,away=(int(x) for x in str(key).split(",",1))
            n=int(count)
        except (TypeError,ValueError):
            raise SystemExit("V2K_ATTEMPT3_JOINT_SCORE_HIST_INVALID")
        if n<0:
            raise SystemExit("V2K_ATTEMPT3_JOINT_SCORE_HIST_INVALID")
        pairs[(home,away)]+=n
    if not pairs:
        raise SystemExit("V2K_ATTEMPT3_JOINT_SCORE_HIST_MISSING")
    return pairs

def evaluate(shards,schedule,contract):
    games={}; seen=defaultdict(set)
    root_seed=int((contract.get("simulation") or {})["root_seed"])
    for s in shards:
        if s.get("schema")!=SHARD_SCHEMA or int(s.get("root_seed"))!=root_seed:
            raise SystemExit("V2K_ATTEMPT3_SHARD_IDENTITY_INVALID")
        seen[(s["fold_id"],s["shard_count"])].add(s["shard_index"])
        for g in s["games"]:
            if g["game_id"] in games:
                raise SystemExit("V2K_ATTEMPT3_DUPLICATE_GAME:"+g["game_id"])
            if g["paths"]!=s["paths_per_game"]:
                raise SystemExit("V2K_ATTEMPT3_PATH_COUNT_INCONSISTENT")
            games[g["game_id"]]=g
    for (fold_id,count),idx in seen.items():
        if idx!=set(range(count)):
            raise SystemExit(f"V2K_ATTEMPT3_SHARDS_INCOMPLETE:{fold_id}")
    expected={gid for gid,row in schedule.items() if 2021<=row["season"]<=2025}
    if set(games)!=expected:
        raise SystemExit(f"V2K_ATTEMPT3_EVALUATED_GAME_SET_MISMATCH:missing={len(expected-set(games))}:extra={len(set(games)-expected)}")
    if {f["fold_id"] for f in contract["fold_plan"]["folds"]}!={k[0] for k in seen}:
        raise SystemExit("V2K_ATTEMPT3_FOLD_SET_MISMATCH")

    rows=[]; key_sum={k:0.0 for k in KEYS}
    for gid in sorted(games):
        g=games[gid]; sched=schedule[gid]
        if (g["home_team"],g["away_team"])!=(sched["home_team"],sched["away_team"]):
            raise SystemExit("V2K_ATTEMPT3_HOME_AWAY_DRIFT:"+gid)
        mh=a1._hist(g["margin_hist"]); th=a1._hist(g["total_hist"])
        pairs=_score_pairs(g.get("score_hist") or {})
        n=sum(c for _,c in mh)
        if sum(pairs.values())!=n:
            raise SystemExit("V2K_ATTEMPT3_JOINT_SCORE_PATH_COUNT_MISMATCH:"+gid)
        pm=Counter(); pt=Counter()
        for (h,a),count in pairs.items():
            pm[h-a]+=count; pt[h+a]+=count
        if pm!=Counter(dict(mh)) or pt!=Counter(dict(th)):
            raise SystemExit("V2K_ATTEMPT3_JOINT_SCORE_MARGINAL_MISMATCH:"+gid)
        for k in KEYS:
            key_sum[k]+=sum(c for v,c in mh if v==k)/n
        m=sched["_market"]; margin=sched["home_score"]-sched["away_score"]; total=sched["home_score"]+sched["away_score"]
        sl,tl=m["spread_line"],m["total_line"]
        mean_home=sum(h*c for (h,_),c in pairs.items())/n
        mean_away=sum(a*c for (_,a),c in pairs.items())/n
        rows.append({
            "game_id":gid,"season":sched["season"],"week":sched["week"],
            "home_score":sched["home_score"],"away_score":sched["away_score"],
            "spread_line":sl,"total_line":tl,
            "home_cover_outcome":None if sl is None or margin==sl else int(margin>sl),
            "over_outcome":None if tl is None or total==tl else int(total>tl),
            "home_win_outcome":None if sched["home_score"]==sched["away_score"] else int(sched["home_score"]>sched["away_score"]),
            "m1_home_cover_prob":a1._novig(m["home_spread_odds"],m["away_spread_odds"]),
            "m1_over_prob":a1._novig(m["over_odds"],m["under_odds"]),
            "m2_home_cover_prob":a1._over_prob(mh,sl),
            "m2_over_prob":a1._over_prob(th,tl),
            "candidate_home_win_prob":a1._over_prob(mh,0.0),
            "sim_mean_margin":sum(v*c for v,c in mh)/n,
            "sim_mean_total":sum(v*c for v,c in th)/n,
            "sim_mean_home_score":mean_home,"sim_mean_away_score":mean_away,
        })

    acc=contract["acceptance"]
    pred_gate=acc["predictive"]
    calibrated=calibrate_nfl_evaluations(rows,min_fit_seasons=MIN_CALIBRATION_FIT_SEASONS)
    calibration=build_calibration_evidence(
        calibrated,bins=CALIBRATION_BINS,min_bin_n=CALIBRATION_MIN_BIN_N,
        max_bin_deviation_threshold=float(pred_gate["calibration_max_nonempty_bin_deviation"]),
    )
    specs={
        "spread":("home_cover_outcome","m1_home_cover_prob","m2_home_cover_calibrated_prob"),
        "total":("over_outcome","m1_over_prob","m2_over_calibrated_prob"),
    }
    folds=[]; predictive={}
    for market,(outcome_key,base_key,cand_key) in specs.items():
        wins=total_folds=0
        for season in sorted({r["season"] for r in calibrated}):
            comp=[r for r in calibrated if r["season"]==season and r.get(outcome_key) in (0,1)
                  and r.get(base_key) is not None and r.get(cand_key) is not None]
            if not comp:
                continue
            bll=a1._log_loss([(r[outcome_key],r[base_key]) for r in comp])
            cll=a1._log_loss([(r[outcome_key],r[cand_key]) for r in comp])
            beat=cll<bll; wins+=int(beat); total_folds+=1
            folds.append({"season":season,"market":market,"n":len(comp),"baseline_log_loss":bll,
                          "candidate_log_loss":cll,"candidate_beats_baseline":beat})
        rate=wins/total_folds if total_folds else 0.0
        cal=calibration[market]
        cal_pass=cal["max_bin_deviation"] is not None and cal["max_bin_deviation"]<=float(pred_gate["calibration_max_nonempty_bin_deviation"])
        fold_pass=bool(total_folds and rate>=float(pred_gate["minimum_fold_win_rate"]))
        predictive[market]={
            "fold_wins":wins,"fold_total":total_folds,"fold_win_rate":rate,
            "required_fold_win_rate":float(pred_gate["minimum_fold_win_rate"]),
            "fold_win_pass":fold_pass,
            "calibration_max_bin_deviation":cal["max_bin_deviation"],
            "calibration_pass":cal_pass,
            "pass":fold_pass and cal_pass,
        }

    n_games=len(games)
    reference=_load_json(REFERENCE_PATH)["reference"]["signed_margin_mass"]
    key_prob={str(k):key_sum[k]/n_games for k in KEYS}
    key_err={str(k):abs(key_prob[str(k)]-float(reference[str(k)])) for k in KEYS}
    key_rmse=sqrt(sum(e*e for e in key_err.values())/len(KEYS))
    spread_slope=evaluate_calibration_truth_gate(calibration["spread"]).to_dict()
    slope=spread_slope.get("slope")
    slope_metric=None if slope is None else abs(float(slope)-1.0)
    struct_gate=acc["structural"]
    structural={
        "candidate_signed_key_probability":key_prob,
        "reference_signed_key_probability":{str(k):float(reference[str(k)]) for k in KEYS},
        "abs_error_by_key":key_err,
        "per_key_tolerance":float(struct_gate["absolute_signed_key_mass_error_max"]),
        "per_key_tolerance_pass":all(e<=float(struct_gate["absolute_signed_key_mass_error_max"]) for e in key_err.values()),
        "candidate_signed_key_mass_rmse":key_rmse,
        "control_signed_key_mass_rmse":float(struct_gate["control_signed_key_mass_rmse"]),
        "key_rmse_improves_on_control":key_rmse<float(struct_gate["control_signed_key_mass_rmse"]),
        "candidate_spread_calibration_slope":slope,
        "candidate_calibration_slope_metric":slope_metric,
        "control_calibration_slope_metric":float(struct_gate["control_calibration_slope_metric"]),
        "slope_improves_on_control":slope_metric is not None and slope_metric<float(struct_gate["control_calibration_slope_metric"]),
        "slope_gate_detail":spread_slope,
    }
    structural["pass"]=(
        structural["per_key_tolerance_pass"] and structural["key_rmse_improves_on_control"]
        and structural["slope_improves_on_control"]
    )

    ml=[r for r in rows if r["home_win_outcome"] in (0,1) and r["candidate_home_win_prob"] is not None]
    ml_pairs=[(r["home_win_outcome"],r["candidate_home_win_prob"]) for r in ml]
    team_errors=[]
    for r in rows:
        team_errors.extend([r["sim_mean_home_score"]-r["home_score"],r["sim_mean_away_score"]-r["away_score"]])
    score_derived={
        "moneyline":{
            "scope":"BINARY_HOME_WIN_DIAGNOSTIC_TIES_EXCLUDED",
            "reference":"UNINFORMATIVE_0.5_NOT_MARKET_BASELINE",
            "overall":{
                "n":len(ml_pairs),
                "candidate_log_loss":a1._log_loss(ml_pairs) if ml_pairs else None,
                "reference_0_5_log_loss":a1._log_loss([(o,0.5) for o,_ in ml_pairs]) if ml_pairs else None,
                "candidate_brier":sum((float(p)-float(o))**2 for o,p in ml_pairs)/len(ml_pairs) if ml_pairs else None,
                "reference_0_5_brier":sum((0.5-float(o))**2 for o,_ in ml_pairs)/len(ml_pairs) if ml_pairs else None,
            },
        },
        "team_total":{
            "scope":"CONTINUOUS_TEAM_SCORE_DIAGNOSTIC_NOT_BOOK_LINE",
            "overall":{
                "n_team_scores":len(team_errors),
                "mae":sum(abs(e) for e in team_errors)/len(team_errors) if team_errors else None,
                "rmse":sqrt(sum(e*e for e in team_errors)/len(team_errors)) if team_errors else None,
            },
        },
    }
    overall=structural["pass"] and all(v["pass"] for v in predictive.values())
    return {
        "schema":RESULT_SCHEMA,"candidate_family":contract["candidate_family"],
        "verdict":"ATTEMPT3_PASS" if overall else "ATTEMPT3_FAIL",
        "predictive_gate":predictive,"folds":folds,"calibration_evidence":calibration,
        "structural_gate":structural,"score_derived_diagnostics":score_derived,
        "evaluated_game_count":n_games,
        "sportsbook_prices_consumed_in_fit":False,
        "sportsbook_prices_consumed_in_evaluation_only":True,
        "authority":{"model_p":False,"pricing":False,"promotion":False,"staking":False,
                     "production_release":False,"official":False,"untouched_readout":False},
    }
