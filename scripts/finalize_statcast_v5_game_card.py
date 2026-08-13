#!/usr/bin/env python3
"""Turn a fresh deployed V5 GAME attestation into the official Full Model card."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from sportsedge.full_model_status import build_required_market_status
from sportsedge.game_risk_guard import GLOBAL_MIN_EDGE, RISK_GATE_VERSION, apply_game_risk_guard
from sportsedge.mlb_source import fetch_schedule, parse_game_start
from sportsedge.truth_gate import decide_bet

ATT=Path('artifacts/live_statcast_v5_game_attestation.json')
LEGACY=Path('config/deployments.json')
STRICT=Path('config/statcast_v5_deployments.json')
OUT=Path('artifacts/live_statcast_v5_full_model_card.json')


def load(p:Path): return json.loads(p.read_text())


def main()->int:
    a=load(ATT); legacy=load(LEGACY); strict=load(STRICT); now=datetime.now(timezone.utc)
    generated=datetime.fromisoformat(str(a['generated_at_utc']).replace('Z','+00:00')).astimezone(timezone.utc)
    age=(now-generated).total_seconds()
    if age<0 or age>60: raise SystemExit(f'V5_ATTESTATION_TOO_OLD_FOR_CARD:{age:.3f}')
    if a.get('model_p_sportsbook_independent') is not True: raise SystemExit('MODEL_P_INDEPENDENCE_NOT_ATTESTED')
    for m in ('MONEYLINE','RUN_LINE','TOTALS'):
        row=(strict.get('markets') or {}).get(m) or {}
        if row.get('eligible') is not True: raise SystemExit('V5_GAME_MARKET_NOT_DEPLOYED:'+m)

    slate=str(a['slate_date_ct']); schedule=fetch_schedule(slate,now=now); live={str(g.game_pk):g for g in schedule}
    rows=[]; quotes=[]
    for game in a.get('games') or []:
        if game.get('status')!='SCORED_V5_ATTESTATION': continue
        gid=str(game['game_id']); snap=live.get(gid)
        if snap is None or snap.status!='Preview' or now>=parse_game_start(snap.game_date): continue
        context=game.get('pregame_context')
        if not isinstance(context,dict): raise SystemExit('PREGAME_CONTEXT_MISSING:'+gid)
        for c in game.get('candidates') or []:
            if c.get('model_p') is None or c.get('american_odds') is None: continue
            d=decide_bet(float(c['model_p']),float(c['american_odds']),bound=True,fresh=True,deployed=True,min_edge=GLOBAL_MIN_EDGE)
            row={
                **c,
                'game_id':gid,'away':game.get('away'),'home':game.get('home'),
                'away_lineup_1_9':game.get('away_lineup_1_9'),'home_lineup_1_9':game.get('home_lineup_1_9'),
                'away_lineup_basis':game.get('away_full_lineup_basis'),'home_lineup_basis':game.get('home_full_lineup_basis'),
                'pregame_context':context,
                'bet_status':d.bet_status,'implied_probability':d.implied_probability,
                'edge':d.edge,'ev_per_dollar':d.ev_per_dollar,'kelly_fraction':d.kelly_fraction,
                'artifact_version':'GAME_SCORE_V5_STATCAST','n_sims':a['n_sims'],
                'statcast_contract':'SPORTSEDGE_STATCAST_V1',
                'attestation_status':'LIVE_ATTESTED_DEPLOYED',
                'deployment_run_id':strict.get('promotion_run_id'),
            }
            rows.append(row)
            quotes.append({'market':c['market'],'game_id':gid})

    rows=apply_game_risk_guard(rows)
    official=sorted((r for r in rows if r['bet_status']=='OFFICIAL_BET'),key=lambda r:(r['ev_per_dollar'],r['edge']),reverse=True)
    status=build_required_market_status(legacy_registry=legacy,strict_registry=strict,quote_rows=quotes,card_rows=rows,source_failures=[])
    payload={
        'schema_version':'sportsedge_v5_full_model_card_v3_full_context',
        'generated_at_utc':now.isoformat(),
        'source_attestation_generated_at_utc':a['generated_at_utc'],
        'slate_date_ct':slate,
        'game_artifact_sha256':a['game_artifact_sha256'],
        'contact_transformer_sha256':a['contact_transformer_sha256'],
        'base_state_end_2025_sha256':a['base_state_end_2025_sha256'],
        'n_sims':a['n_sims'],
        'context_schema_version':a.get('context_schema_version'),
        'context_sources':a.get('context_sources'),
        'context_model_p_consumption':a.get('context_model_p_consumption'),
        'official_bets_count':len(official),
        'best_bets':official,
        'game_candidates':rows,
        'required_market_status':status,
        'risk_gate':{
            'version':RISK_GATE_VERSION,
            'model_p_modified':False,
            'sportsbook_used_as_model_feature':False,
            'global_min_edge':GLOBAL_MIN_EDGE,
            'purpose':'downstream wager-selection safety while ML tail validation is pending',
        },
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'official_bets_count':len(official),'best_bets':[{'market':x['market'],'selection':x.get('selection'),'line':x.get('line'),'odds':x['american_odds'],'model_p':x['model_p'],'ev':x['ev_per_dollar'],'risk_gate_reason':x.get('risk_gate_reason')} for x in official[:10]],'market_status':status['markets'],'context_model_p_consumption':payload['context_model_p_consumption'],'risk_gate':payload['risk_gate']},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
