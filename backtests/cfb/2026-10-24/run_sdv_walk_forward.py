#!/usr/bin/env python3
"""Chronological SDV score diagnostic, NOT PIT validation or betting evidence.

Uses the existing model family, alpha and constants unchanged. Retrospective
weather/source provenance and absent paired closes prevent a market verdict.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from sportsedge.sports.cfb.sportsdataverse_candidate_model import fit_native_score_model


def run(rows):
    seasons = sorted({int(r['season']) for r in rows})
    diagnostics = []
    metadata_violations = []
    for row in rows:
        for side in ['home', 'away']:
            current = row.get(side + '_current_metrics') or {}
            if (int(current.get('season', row['season'])) > int(row['season'])
                    or (int(current.get('season', row['season'])) == int(row['season'])
                        and int(current.get('through_week', 0)) >= int(row['week']))):
                metadata_violations.append(str(row['game_id']))
    if metadata_violations:
        raise ValueError('CURRENT_FEATURE_CLOCK_VIOLATIONS:' + str(len(metadata_violations)))
    for season in seasons[1:]:
        train = [r for r in rows if int(r['season']) < season]
        test = [r for r in rows if int(r['season']) == season]
        assert max(int(r['season']) for r in train) < season
        model = fit_native_score_model(train, family='PRIOR_CURRENT_BLEND',
                                       ridge_alpha=300.0, constants={'prior_equivalent_games': 4})
        errors_total, errors_margin = [], []
        for row in test:
            home, away = model.predict_means(row, {'prior_equivalent_games': 4})
            errors_total.append(home + away - float(row['home_points']) - float(row['away_points']))
            errors_margin.append(home - away - float(row['home_points']) + float(row['away_points']))
        mean = lambda xs: sum(xs) / len(xs)
        diagnostics.append({'season': season, 'train_n': len(train), 'test_n': len(test),
                            'train_seasons': sorted({int(r['season']) for r in train}),
                            'holdout': season == seasons[-1],
                            'total_bias_predicted_minus_actual': mean(errors_total),
                            'total_mae': mean([abs(v) for v in errors_total]),
                            'margin_mae': mean([abs(v) for v in errors_margin])})
    return {'attempt': 1, 'model': 'SDV_PRIOR_CURRENT_BLEND',
            'status': 'RECONSTRUCTED_SCORE_DIAGNOSTIC_NOT_PIT_VALIDATION',
            'row_count': len(rows), 'holdout_season': seasons[-1],
            'chronological_training_check': 'PASS', 'current_week_metadata_violations': 0,
            'source_provenance': dict(Counter(r.get('provenance_class', 'MISSING') for r in rows)),
            'leakage_check': 'NOT_CLEARED_HISTORICAL_WEATHER_AVAILABILITY_UNPROVEN',
            'season_diagnostics': diagnostics,
            'markets': {m: {'verdict': 'INSUFFICIENT_DATA', 'paired_n': 0,
                        'brier_vs_close': None, 'log_loss_vs_close': None,
                        'calibration_slope': None, 'calibration_intercept': None, 'ece': None,
                        'mean_clv': None, 'roi_at_logged_price': None, 'bets_ev_ge_2pct': None,
                        'reason': 'NO_PAIRED_HISTORICAL_CLOSES_OR_ENTRY_QUOTES; PIT_NOT_CLEARED'}
                        for m in ['MONEYLINE', 'SPREAD', 'TOTAL']},
            'promotion_changed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.rows.read_bytes()
    result = run(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    result['code_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['model_code_sha256'] = hashlib.sha256((ROOT / 'sportsedge/sports/cfb/sportsdataverse_candidate_model.py').read_bytes()).hexdigest()
    import numpy
    result['numpy_version'] = numpy.__version__
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result['season_diagnostics'][-1]))
