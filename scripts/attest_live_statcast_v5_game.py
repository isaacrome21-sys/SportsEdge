#!/usr/bin/env python3
"""Attest live SportsEdge GAME_SCORE_V5_STATCAST on the current Chicago MLB slate.

This is an inference/parity attestation, not a deployment override. It verifies
exact frozen model/transformer hashes, a separately hashed end-2025 rolling
Statcast state, rolls that state only with prior 2026 contacts, binds official
MLB starters and confirmed batting slots 1-3, runs fixed-seed Monte Carlo, and
only then joins legitimate DraftKings prices. Sportsbook values never enter
Model_P.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
from zoneinfo import ZoneInfo
import joblib

from scripts.rebuild_statcast_v5_strict import regular_season_bounds
from sportsedge.espn_game_odds_source import fetch_espn_draftkings_game_quotes
from sportsedge.game_history_live import build_live_game_feature_rows
from sportsedge.game_live_features import RUN_FEATURES
from sportsedge.game_score_live import assert_no_sportsbook_contamination, price_game_quote, simulate_game
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule, fetch_team_abbreviation, parse_confirmed_lineup, parse_game_start
from sportsedge.statcast_contract import GAME_STATCAST_FEATURES, require_statcast_artifact
from sportsedge.statcast_v5_live import assemble_live_statcast_features, resolved_top3
from sportsedge.statcast_v5_live_source import load_hashed_state, roll_state_to_cutoff
from sportsedge.truth_gate import decide_bet

CT=ZoneInfo('America/Chicago')

def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()

def _load_validation(root:Path)->dict:
    p=root/'validation.json'
    if not p.is_file(): raise SystemExit('STATCAST_V5_VALIDATION_MISSING')
    v=json.loads(p.read_text())
    for market in ('MONEYLINE','RUN_LINE','TOTALS'):
        if (v.get('passes') or {}).get(market) is not True: raise SystemExit('STATCAST_V5_GAME_HOLDOUT_NOT_PASSED:'+market)
    return v

def _load_state_record(root:Path)->dict:
    p=root/'base_state_manifest.json'
    if not p.is_file(): raise SystemExit('STATCAST_V5_BASE_STATE_MANIFEST_MISSING')
    r=json.loads(p.read_text())
    if r.get('model_refit_performed') is not False or r.get('sportsbook_data_used') is not False:
        raise SystemExit('STATCAST_V5_BASE_STATE_PROVENANCE_INVALID')
    return r

def _verify(root:Path,v:dict,state_record:dict):
    gp=root/'sportsedge_game_score_v5_statcast.joblib'; tp=root/'sportsedge_contact_transformer_v1.joblib'; sp=root/'sportsedge_statcast_state_end_2025.joblib'
    for p in (gp,tp,sp):
        if not p.is_file(): raise SystemExit('STATCAST_V5_RUNTIME_FILE_MISSING:'+str(p))
    expected_game=os.getenv('SPORTSEDGE_EXPECTED_V5_GAME_SHA256')
    expected_transformer=os.getenv('SPORTSEDGE_EXPECTED_V5_TRANSFORMER_SHA256')
    if sha(gp)!=v.get('game_artifact_sha256') or (expected_game and sha(gp)!=expected_game): raise SystemExit('STATCAST_V5_GAME_SHA_MISMATCH')
    if sha(tp)!=v.get('contact_transformer_sha256') or (expected_transformer and sha(tp)!=expected_transformer): raise SystemExit('STATCAST_V5_TRANSFORMER_SHA_MISMATCH')
    state_sha=str(state_record.get('base_state_end_2025_sha256') or '')
    if not state_sha or sha(sp)!=state_sha: raise SystemExit('STATCAST_V5_BASE_STATE_SHA_MISMATCH')
    if state_record.get('contact_transformer_sha256')!=sha(tp): raise SystemExit('STATCAST_V5_BASE_STATE_TRANSFORMER_MISMATCH')
    artifact=joblib.load(gp); transformer=joblib.load(tp)
    require_statcast_artifact(artifact,kind='game')
    expected=tuple(RUN_FEATURES)+tuple(GAME_STATCAST_FEATURES)
    if tuple(artifact.get('run_features') or ())!=expected: raise SystemExit('STATCAST_V5_LIVE_FEATURE_CONTRACT_MISMATCH')
    state=load_hashed_state(sp,state_sha)
    return artifact,transformer,state,gp,tp,sp,state_sha

def main()->int:
    now=datetime.now(timezone.utc); slate=now.astimezone(CT).date()
    root=Path(os.getenv('SPORTSEDGE_STATCAST_V5_OUT','artifacts/statcast-v5-game'))
    n_sims=int(os.getenv('SPORTSEDGE_V5_LIVE_SIMS','250000'))
    if n_sims<7000: raise SystemExit('STATCAST_V5_LIVE_SIMS_TOO_SMALL')
    v=_load_validation(root); state_record=_load_state_record(root)
    artifact,transformer,base_state,gp,tp,sp,state_sha=_verify(root,v,state_record)
    schedule=fetch_schedule(slate.isoformat(),now=now)
    season_start,_=regular_season_bounds(2026,Path('.cache/sportsedge/statcast-v5-live/bounds'))
    state=roll_state_to_cutoff(base_state=base_state,transformer=transformer,year=2026,start_date=season_start,cutoff_date=slate,cache_dir=Path('.cache/sportsedge/statcast-v5-live/savant'))
    baseline,history_exclusions=build_live_game_feature_rows(slate_date=slate,schedule=schedule,cache_dir=Path('.cache/sportsedge/mlb-history/game-v5'))
    baseline_by_game={str(x['game_id']):x for x in baseline}

    # Price acquisition is downstream of all Model_P state/features.
    price_snapshot=fetch_espn_draftkings_game_quotes(slate_date=slate,schedule=schedule,retrieved_at=now)
    quotes_by_game={}
    for q in price_snapshot.quotes: quotes_by_game.setdefault(str(q['game_id']),[]).append(q)

    games=[]; scored=0
    for g in schedule:
        gid=str(g.game_pk); start=parse_game_start(g.game_date)
        if g.status!='Preview' or now>=start:
            games.append({'game_id':gid,'away':g.away_name,'home':g.home_name,'status':'BLOCKED','reason':'GAME_ALREADY_STARTED_OR_NOT_PREGAME'}); continue
        try:
            if not g.away_probable_pitcher_id or not g.home_probable_pitcher_id: raise ValueError('PROBABLE_PITCHER_UNRESOLVED')
            box=fetch_boxscore(g.game_pk)
            away_top3=resolved_top3(parse_confirmed_lineup(box,'away')); home_top3=resolved_top3(parse_confirmed_lineup(box,'home'))
            away_abbr=fetch_team_abbreviation(g.away_id); home_abbr=fetch_team_abbreviation(g.home_id)
            sf=assemble_live_statcast_features(state,away_team=away_abbr,home_team=home_abbr,away_starter_id=int(g.away_probable_pitcher_id),home_starter_id=int(g.home_probable_pitcher_id),away_top3=away_top3,home_top3=home_top3)
            base=baseline_by_game[gid]['run_rows']
            rows=[list(base[0])+[float(sf['away'][n]) for n in GAME_STATCAST_FEATURES],list(base[1])+[float(sf['home'][n]) for n in GAME_STATCAST_FEATURES]]
            assert_no_sportsbook_contamination({n:rows[0][i] for i,n in enumerate(artifact['run_features'])})
            sim=simulate_game(artifact,rows,game_id=g.game_pk,n_sims=n_sims)
            candidates=[]
            for q in quotes_by_game.get(gid,[]):
                age=(now-q['retrieved_at']).total_seconds()
                if age<0 or age>int(q['ttl_seconds']):
                    candidates.append({'market':q['market'],'side':q['side'],'status':'BLOCKED','reason':'PRICE_STALE_OR_FUTURE'}); continue
                priced=price_game_quote(sim,q); d=decide_bet(priced['model_p'],q['american_odds'],bound=True,fresh=True,deployed=False,min_edge=0.0)
                candidates.append({'market':q['market'],'side':q['side'],'selection':q.get('selection'),'line':q.get('line'),'american_odds':q['american_odds'],'model_p':priced['model_p'],'edge':d.edge,'ev_per_dollar':d.ev_per_dollar,'attestation_status':'DEPLOYMENT_PENDING','price_source':q.get('source_url')})
            games.append({'game_id':gid,'away':g.away_name,'home':g.home_name,'status':'SCORED_V5_ATTESTATION','away_starter_id':g.away_probable_pitcher_id,'home_starter_id':g.home_probable_pitcher_id,'away_top3':list(away_top3),'home_top3':list(home_top3),'away_mu':sim['away_mu'],'home_mu':sim['home_mu'],'home_ml_p':sim['home_ml_p'],'n_sims':n_sims,'candidates':candidates}); scored+=1
        except Exception as exc:
            games.append({'game_id':gid,'away':g.away_name,'home':g.home_name,'status':'BLOCKED','reason':str(exc)})

    out={'schema_version':'sportsedge_live_statcast_v5_game_attestation_v1','generated_at_utc':now.isoformat(),'slate_date_ct':slate.isoformat(),'engine':'GAME_SCORE_V5_STATCAST','n_sims':n_sims,'game_artifact_sha256':sha(gp),'contact_transformer_sha256':sha(tp),'base_state_end_2025_sha256':state_sha,'holdout_source_commit':'0571a3b0d0d063279840735f88230e9112bed07a','holdout_passes':{k:(v.get('passes') or {}).get(k) for k in ('MONEYLINE','RUN_LINE','TOTALS')},'model_p_sportsbook_independent':True,'price_source':'ESPN_WEB_HEADER_DRAFTKINGS','price_ttl_seconds':60,'price_failures':list(price_snapshot.failures),'history_exclusions_count':len(history_exclusions),'scheduled_games':len(schedule),'scored_pregame_games':scored,'games':games}
    p=Path('artifacts/live_statcast_v5_game_attestation.json'); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(out,indent=2,sort_keys=True,default=str)+'\n')
    print(json.dumps({'scheduled_games':len(schedule),'scored_pregame_games':scored,'artifact':str(p)},indent=2))
    if scored<1: raise SystemExit('STATCAST_V5_LIVE_NO_PREGAME_GAME_SCORED')
    return 0

if __name__=='__main__': raise SystemExit(main())
