#!/usr/bin/env python3
"""Capture pre-first-pitch NRFI/YRFI V6 forward-shadow predictions.

No sportsbook prices are fetched. The output is validation evidence only and is
cryptographically bound to the exact V6 artifact and literal inherited feature
contract. Missing starters/lineups/Statcast evidence block the affected game.

Lineup identity now uses the same hierarchy as deployed GAME V5: confirmed MLB,
then a fresh configured provider, then SportsEdge's deterministic projection from
prior confirmed MLB lineups plus the current active roster.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib, json, math, os
from pathlib import Path
from zoneinfo import ZoneInfo
import joblib

from scripts.attest_live_statcast_v5_game import _load_state_record, _projection_index, _top3
from scripts.rebuild_statcast_v5_strict import regular_season_bounds
from sportsedge.forward_shadow import ShadowPrediction, canonical_json, write_prediction_ledger
from sportsedge.game_history_live import build_live_game_feature_rows
from sportsedge.mlb_lineup_projection import build_slate_projections
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule, fetch_team_abbreviation, parse_game_start
from sportsedge.nrfi_live import assert_no_sportsbook_contamination, first_inning_model_p
from sportsedge.statcast_contract import NRFI_STATCAST_FEATURES, require_statcast_artifact
from sportsedge.statcast_v5_live import assemble_live_statcast_features
from sportsedge.statcast_v5_live_source import load_hashed_state, roll_state_to_cutoff

CT=ZoneInfo("America/Chicago")
EXPECTED_V6_SHA=os.getenv("SPORTSEDGE_NRFI_V6_SHA256","0bdf71e272e406611e241e2427904f3c8e3a9405700f440bedacf0b74ed1580e")
EXPECTED_TRANSFORMER_SHA="bf61487279ac9a506318e9dfa078a866450dd4e363b1d06356e58852954133b2"


def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()

def _logit(p:float)->float:
    q=min(max(float(p),1e-6),1-1e-6); return math.log(q/(1-q))

def _expit(x:float)->float: return 1/(1+math.exp(-float(x)))

def _feature_contract_sha(features)->str:
    return hashlib.sha256(canonical_json(list(features))).hexdigest()


def _top3_with_mlb_fallback(*, box, side, game, projected, mlb_projected, now):
    try:
        top3, basis = _top3(
            box=box, side=side, game_pk=game.game_pk,
            team_id=game.away_id if side == "away" else game.home_id,
            projected=projected, now=now,
        )
        return top3, basis, ()
    except Exception as primary_exc:
        team_id = int(game.away_id if side == "away" else game.home_id)
        internal = mlb_projected.get(team_id)
        if internal is None:
            raise ValueError(f"TOP3_UNRESOLVED_NO_ADMISSIBLE_PROJECTION:{side}:{primary_exc}") from primary_exc
        top3 = internal.top3()
        return top3, "PROJECTED_MLB_PRIOR_CONFIRMED", tuple(int(x) for x in internal.source_game_pks)


def main()->int:
    now=datetime.now(timezone.utc); slate=now.astimezone(CT).date()
    v6p=Path(os.getenv("SPORTSEDGE_NRFI_V6_ARTIFACT","artifacts/nrfi-v6-shadow/sportsedge_nrfi_v6_shadow.joblib"))
    root=Path(os.getenv("SPORTSEDGE_STATCAST_V5_OUT","artifacts/statcast-v5-game"))
    if not v6p.is_file() or sha(v6p)!=EXPECTED_V6_SHA: raise SystemExit("NRFI_V6_ARTIFACT_SHA_MISMATCH")
    v6=joblib.load(v6p); base=v6.get("base_artifact")
    if not isinstance(base,dict): raise SystemExit("NRFI_V6_BASE_ARTIFACT_MISSING")
    require_statcast_artifact(base,kind="nrfi")
    features=tuple(v6.get("features") or ())
    if features!=tuple(base.get("features") or ()): raise SystemExit("NRFI_V6_INHERITED_FEATURE_CONTRACT_MISMATCH")
    if any(f not in features for f in NRFI_STATCAST_FEATURES): raise SystemExit("NRFI_V6_STATCAST_FEATURE_MISSING")
    offset=float(v6.get("logit_intercept"))
    if v6.get("deployment_eligible") is not False: raise SystemExit("NRFI_V6_SHADOW_ARTIFACT_ILLEGALLY_DEPLOYED")

    tp=root/"sportsedge_contact_transformer_v1.joblib"; sp=root/"sportsedge_statcast_state_end_2025.joblib"
    state_record=_load_state_record(root)
    if sha(tp)!=EXPECTED_TRANSFORMER_SHA: raise SystemExit("NRFI_V6_TRANSFORMER_SHA_MISMATCH")
    state_sha=str(state_record.get("base_state_end_2025_sha256") or "")
    if not state_sha or sha(sp)!=state_sha: raise SystemExit("NRFI_V6_BASE_STATE_SHA_MISMATCH")
    transformer=joblib.load(tp); base_state=load_hashed_state(sp,state_sha)

    schedule=fetch_schedule(slate.isoformat(),now=now)
    projected,projection_source_status=_projection_index(now)
    team_ids={int(x.away_id) for x in schedule}|{int(x.home_id) for x in schedule}
    mlb_projected,mlb_projection_failures=build_slate_projections(team_ids=team_ids,slate_date=slate,now=now)
    season_start,_=regular_season_bounds(2026,Path(".cache/sportsedge/nrfi-v6-shadow/bounds"))
    state=roll_state_to_cutoff(base_state=base_state,transformer=transformer,year=2026,start_date=season_start,cutoff_date=slate,cache_dir=Path(".cache/sportsedge/nrfi-v6-shadow/savant"))
    baseline,history_exclusions=build_live_game_feature_rows(slate_date=slate,schedule=schedule,cache_dir=Path(".cache/sportsedge/nrfi-v6-shadow/history"))
    by_game={str(x["game_id"]):x for x in baseline}

    rows=[]; blocked=[]
    contract_sha=_feature_contract_sha(features)
    source_cutoff=(slate-timedelta(days=1)).isoformat()
    for g in schedule:
        gid=str(g.game_pk); start=parse_game_start(g.game_date)
        if g.status!="Preview" or now>=start:
            blocked.append({"game_id":gid,"reason":"GAME_ALREADY_STARTED_OR_NOT_PREGAME"}); continue
        try:
            if not g.away_probable_pitcher_id or not g.home_probable_pitcher_id: raise ValueError("PROBABLE_PITCHER_UNRESOLVED")
            box=fetch_boxscore(g.game_pk)
            away_top3,away_basis,away_source_games=_top3_with_mlb_fallback(box=box,side="away",game=g,projected=projected,mlb_projected=mlb_projected,now=now)
            home_top3,home_basis,home_source_games=_top3_with_mlb_fallback(box=box,side="home",game=g,projected=projected,mlb_projected=mlb_projected,now=now)
            sf=assemble_live_statcast_features(state,away_team=fetch_team_abbreviation(g.away_id),home_team=fetch_team_abbreviation(g.home_id),away_starter_id=int(g.away_probable_pitcher_id),home_starter_id=int(g.home_probable_pitcher_id),away_top3=away_top3,home_top3=home_top3)
            fi=list(by_game[gid]["fi_row"])+[float(sf["first_inning"][n]) for n in NRFI_STATCAST_FEATURES]
            if len(fi)!=len(features): raise ValueError("NRFI_V6_LIVE_FEATURE_LENGTH_MISMATCH")
            assert_no_sportsbook_contamination({name:fi[i] for i,name in enumerate(features)})
            b=first_inning_model_p(base,fi)
            yrfi=min(max(_expit(_logit(b["YRFI"])+offset),.001),.999); nrfi=1-yrfi
            identity={"away_team_id":int(g.away_id),"home_team_id":int(g.home_id),"away_starter_id":int(g.away_probable_pitcher_id),"home_starter_id":int(g.home_probable_pitcher_id),"away_top3":list(away_top3),"home_top3":list(home_top3)}
            provenance={"away_lineup_basis":away_basis,"home_lineup_basis":home_basis,"away_lineup_source_game_pks":list(away_source_games),"home_lineup_source_game_pks":list(home_source_games),"projection_source_status":projection_source_status,"base_v5_yrfi_p":float(b["YRFI"]),"statcast_state_end_2025_sha256":state_sha,"contact_transformer_sha256":EXPECTED_TRANSFORMER_SHA}
            for market,p,side in (("YRFI",yrfi,"OVER"),("NRFI",nrfi,"UNDER")):
                rows.append(ShadowPrediction(market=market,game_id=gid,entity_id=gid,side=side,line=.5,model_p=float(p),generated_at_utc=now.isoformat(),cutoff_at_utc=start.isoformat(),model_artifact_sha256=EXPECTED_V6_SHA,feature_contract_sha256=contract_sha,source_cutoff=source_cutoff,model_version="NRFI_V6_FORWARD_SHADOW",identity=identity,provenance=provenance))
        except Exception as exc:
            blocked.append({"game_id":gid,"reason":f"{type(exc).__name__}:{exc}"})

    out=Path("artifacts/forward-shadow/nrfi_v6_predictions.json"); man=Path("artifacts/forward-shadow/nrfi_v6_manifest.json")
    write_prediction_ledger(rows,output=out,manifest=man,generated_at=now)
    status={"schema_version":"nrfi_v6_shadow_capture_v2_mlb_projection_fallback","generated_at_utc":now.isoformat(),"slate_date_ct":slate.isoformat(),"candidate_sha256":EXPECTED_V6_SHA,"feature_contract_sha256":contract_sha,"predictions":len(rows),"games_predicted":len(rows)//2,"scheduled_games":len(schedule),"blocked":blocked,"history_exclusions_count":len(history_exclusions),"projection_source_status":projection_source_status,"mlb_prior_projection_teams":len(mlb_projected),"mlb_prior_projection_failures":{str(k):v for k,v in sorted(mlb_projection_failures.items())},"sportsbook_data_used":False,"deployment_eligible":False}
    Path("artifacts/forward-shadow/nrfi_v6_status.json").write_bytes(canonical_json(status))
    print(json.dumps({"games_predicted":len(rows)//2,"scheduled_games":len(schedule),"blocked":len(blocked),"mlb_prior_projection_teams":len(mlb_projected),"candidate_sha256":EXPECTED_V6_SHA},indent=2))
    if not rows: raise SystemExit("NRFI_V6_SHADOW_NO_PREGAME_PREDICTIONS")
    return 0

if __name__=="__main__": raise SystemExit(main())
