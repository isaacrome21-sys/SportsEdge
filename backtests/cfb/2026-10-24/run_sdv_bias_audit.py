#!/usr/bin/env python3
"""Attempt 2: unchanged SDV model, descriptive bias/baseline and source audit."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model


def run(path):
    rows = json.loads(path.read_bytes()); out = []
    for season in sorted({int(r['season']) for r in rows})[1:]:
        train = [r for r in rows if int(r['season']) < season]
        test = [r for r in rows if int(r['season']) == season]
        model = fit_native_score_model(train, family='PRIOR_CURRENT_BLEND', ridge_alpha=300.0, constants={'prior_equivalent_games':4})
        pred = np.array([sum(model.predict_means(r, {'prior_equivalent_games':4})) for r in test])
        actual = np.array([r['home_points']+r['away_points'] for r in test])
        out.append({'season':season, 'n':len(test), 'train_n':len(train),
                    'prediction_mean':float(pred.mean()), 'actual_mean':float(actual.mean()),
                    'prediction_sd':float(pred.std()), 'actual_sd':float(actual.std()),
                    'overprediction_n':int((pred>actual).sum()), 'underprediction_n':int((pred<actual).sum()),
                    'bias':float((pred-actual).mean()), 'mae':float(abs(pred-actual).mean()),
                    'flat_28_per_team_baseline_bias':float((56-actual).mean()),
                    'flat_28_per_team_baseline_mae':float(abs(56-actual).mean()),
                    'market_over_under_selection_split':None})
    fields = Counter(k for r in rows for k in (r.get('weather') or {}))
    prior_bad = sum(int((r.get(s+'_prior_metrics') or {}).get('season',r['season'])) >= int(r['season']) for r in rows for s in ['home','away'])
    current_bad = sum(int((r.get(s+'_current_metrics') or {}).get('through_week',0)) >= int(r['week']) for r in rows for s in ['home','away'])
    return {'attempt':2, 'status':'RECONSTRUCTED_SCORE_DIAGNOSTIC_NOT_PIT',
            'attempt1_preserved':True, 'no_tuning':True, 'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'prior_season_metadata_violations':prior_bad, 'current_week_metadata_violations':current_bad,
            'weather_field_counts':dict(fields),
            'weather_issue':'No forecast issuance/availability timestamp in training weather; historical observed values cannot be certified pregame.',
            'season_diagnostics':out,
            'opponent_adjusted_status':'NOT_EXECUTED: SDV rows lack actual kickoff and spread; canonical project() requires both. No fake spread or kickoff supplied.',
            'baseline_note':'Flat 56 is a constant comparator ONLY, not output from CFB_OPPONENT_ADJUSTED_V1.',
            'over_under_note':'Counts compare projections with actual scores, NOT bookmaker lines or recommended bets.',
            'market_verdict':'INSUFFICIENT_DATA', 'promotion_authority':False}


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--rows',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();result=run(args.rows);result['code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result['season_diagnostics'][-1]))
