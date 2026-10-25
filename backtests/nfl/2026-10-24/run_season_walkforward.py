#!/usr/bin/env python3
"""Attempt3: prior-season refits using unchanged Attempt9 routines/alphas.

Score-only diagnostic. Does not borrow frozen probability calibration for newly
refitted forecasts, invent entry prices, or publish forward evidence.
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
from fit_football_baselines import scale, fit
from sportsedge.nfl_attempt9_live_forecast import load_runtime


def run(path):
    raw = path.read_bytes()
    records = list(csv.DictReader(raw.decode().splitlines()))
    games = [dict(r, id=r['game_id'], date=r['gameday'], home=r['home_team'], away=r['away_team'],
                  hs=float(r['home_score']), **{'as':float(r['away_score'])})
             for r in records if r['home_score'] and r['away_score'] and int(r['season'])>=2010]
    assert len({g['id'] for g in games}) == len(games)
    X, ym, yt, _, _, keys = features(games)
    seasons = np.array([int(k[2]['season']) for k in keys])
    artifact = load_runtime()
    reports = []
    # Parameters frozen in original research; 2017-19 selection years excluded.
    # 2026 is latest available season and partial, never called a complete season.
    for year in range(2020, int(seasons.max())+1):
        train, test = seasons < year, seasons == year
        assert seasons[train].max() < seasons[test].min()
        a, b = scale(X[train], X[test])
        report = {'season':year,'train_n':int(train.sum()),'test_n':int(test.sum()),
                  'train_seasons':sorted(set(map(int,seasons[train]))),
                  'latest_season_holdout':year==int(seasons.max()), 'partial_season':year==2026}
        for target, y in [('margin',ym),('total',yt)]:
            alpha = float(artifact['runtime']['targets'][target]['alpha'])
            beta, intercept = fit(a,y[train],alpha)
            pred = b@beta+intercept; actual = y[test]
            report[target] = {'alpha':alpha,'mae':float(abs(pred-actual).mean()),
                              'bias':float((pred-actual).mean()),'prediction_sd':float(pred.std()),
                              'actual_sd':float(actual.std()),
                              'training_mean_baseline_mae':float(abs(y[train].mean()-actual).mean())}
        reports.append(report)
    return {'attempt':3,'status':'RETROSPECTIVE_SCORE_DIAGNOSTIC_NOT_PIT_VALIDATION',
            'source_sha256':hashlib.sha256(raw).hexdigest(),
            'chronological_split_check':'PASS', 'tuning_performed':False,
            'leakage_limit':'Same-day scores excluded by batched feature builder; retrospective source vintage and pregame availability not proven. Previously exposed data is not a newly sealed independent test.',
            'seasons':reports,'market_verdict':'INSUFFICIENT_DATA',
            'probability_metrics':None,'clv':None,'roi':None,'bets_ev_ge_2pct':None,
            'reason':'Score-only fit; no independently validated probability calibration for refits or authenticated entry/close pairs.',
            'production_changed':False}


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--csv',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();result=run(args.csv);result['code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result['seasons'][-2:]))
