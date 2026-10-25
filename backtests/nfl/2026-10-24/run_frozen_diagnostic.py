#!/usr/bin/env python3
"""Frozen Attempt9 seasonal replay; retrospective diagnostic, not admission.

No refit, no synthetic quotes/timestamps, no live/forward evidence writes.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from fit_nfl_recency_attempt9 import features
from sportsedge.nfl_attempt9_live_forecast import load_runtime, load_model_p, raw_forecasts
from sportsedge.sports.nfl.attempt9_model_p import model_probability


def run(path):
    source = list(csv.DictReader(path.open()))
    games = [dict(r, id=r['game_id'], date=r['gameday'], home=r['home_team'],
                  away=r['away_team'], hs=float(r['home_score']), **{'as': float(r['away_score'])})
             for r in source if r['home_score'] and r['away_score']]
    assert len({g['id'] for g in games}) == len(games)
    X, _, _, _, _, keys = features(games)
    runtime, artifact = load_runtime(), load_model_p()
    rows = []
    for x, (_, _, g) in zip(X, keys):
        if int(g['season']) < 2020:
            continue  # frozen fit/calibration use 2010-2019; don't rescore selection years
        pred = raw_forecasts(runtime, x)
        rows.append({'season': int(g['season']), 'id': g['id'], 'pred': pred, 'g': g})
    report = []
    for season in sorted({r['season'] for r in rows}):
        rs = [r for r in rows if r['season'] == season]
        out = {'season': season, 'n': len(rs), 'partial_season': season == 2026,
               'training_end_season': 2016, 'calibration_end_season': 2019}
        for target, field, market, selection in [('margin', 'spread_line', 'spread', 'home'),
                                                 ('total', 'total_line', 'total', 'over')]:
            pp = np.array([r['pred'][target] for r in rs])
            yy = np.array([r['g']['hs'] + (-r['g']['as'] if target == 'margin' else r['g']['as']) for r in rs])
            probs, raw_probs = [], []
            for r in rs:
                v = r['g'][field]
                if not v or float(v).is_integer():
                    continue
                p = model_probability(artifact, market=market, raw_prediction=r['pred'][target],
                                      line=-float(v) if target == 'margin' else float(v), selection=selection)
                probs.append(p['model_p']); raw_probs.append(p['raw_threshold_probability'])
            out[target] = {'bias': float(np.mean(pp-yy)), 'mae': float(np.mean(abs(pp-yy))),
                           'prediction_sd': float(np.std(pp)), 'outcome_sd': float(np.std(yy)),
                           'noninteger_threshold_n': len(probs),
                           'raw_probability_mean_distance_from_half': float(np.mean(abs(np.array(raw_probs)-.5))) if probs else None,
                           'calibrated_probability_mean_distance_from_half': float(np.mean(abs(np.array(probs)-.5))) if probs else None,
                           'probability_fraction_45_to_55pct': float(np.mean((np.array(probs)>=.45)&(np.array(probs)<=.55))) if probs else None}
        report.append(out)
    return {'attempt': 2, 'status': 'FROZEN_MODEL_RETROSPECTIVE_DIAGNOSTIC_NOT_PIT',
            'evaluation': 'Fixed 2010-2016 weights and 2017-2019 calibration, sequential 2020-2026 replay; not expanding-season refit or newly sealed holdout',
            'latest_complete_season': 2025, 'latest_partial_season': 2026,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'runtime_artifact_sha256': runtime['artifact_sha256'],
            'model_p_artifact_sha256': artifact['artifact_sha256'],
            'leakage_check': 'Feature routine batches dates before admitting outcomes; same-date excluded. Retrospective corrected source, not archived pregame features.',
            'market_verdict': 'INSUFFICIENT_DATA',
            'unavailable': ['authenticated paired closing provenance', 'logged entry quote/time', 'multi-season paired prop closes'],
            'brier_vs_close': None, 'log_loss_vs_close': None, 'calibration_slope': None,
            'calibration_intercept': None, 'ece': None, 'mean_clv': None, 'roi_at_logged_price': None,
            'bets_ev_ge_2pct': None, 'seasons': report, 'promotion_authority': False}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--csv', type=Path, required=True); ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(); result = run(args.csv)
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print(json.dumps(result['seasons'][-2:]))
