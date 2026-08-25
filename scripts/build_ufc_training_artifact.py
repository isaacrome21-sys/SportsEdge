#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from math import log
from pathlib import Path
from statistics import mean
from urllib.request import Request, urlopen

from sportsedge.ufc_training import TrainingRow, evaluate, fit_chronological, update_elo

DEFAULT_URL = 'https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2026/2026-07-07/ultimate_ufc_dataset.csv'


def f(row, k, d=0.0):
    try:
        return float(row.get(k) or d)
    except (TypeError, ValueError):
        return d


def _optional_float(row, key):
    try:
        value = row.get(key)
        if value in (None, '', 'NA', 'N/A'):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _american_to_implied(odds):
    if odds is None or odds == 0:
        return None
    return 100.0 / (odds + 100.0) if odds > 0 else (-odds) / ((-odds) + 100.0)


def _market_red_probability(row):
    pr = _american_to_implied(_optional_float(row, 'r_odds'))
    pb = _american_to_implied(_optional_float(row, 'b_odds'))
    if pr is None or pb is None or pr + pb <= 0:
        return None
    return pr / (pr + pb)


def _probability_metrics(probs, ys, bins=10):
    pairs = [(float(p), int(y)) for p, y in zip(probs, ys) if p is not None]
    if not pairs:
        return {'n': 0, 'log_loss': None, 'brier': None, 'accuracy': None, 'calibration_error': None}
    ps = [min(1.0 - 1e-12, max(1e-12, p)) for p, _ in pairs]
    labels = [y for _, y in pairs]
    ll = -mean(y * log(p) + (1-y) * log(1-p) for p, y in zip(ps, labels))
    brier = mean((p-y) ** 2 for p, y in zip(ps, labels))
    accuracy = mean(1.0 if (p >= 0.5) == bool(y) else 0.0 for p, y in zip(ps, labels))
    ce = 0.0
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (k == bins - 1 and p == 1.0)]
        if idx:
            ce += (len(idx) / len(ps)) * abs(mean(ps[i] for i in idx) - mean(labels[i] for i in idx))
    return {'n': len(ps), 'log_loss': ll, 'brier': brier, 'accuracy': accuracy, 'calibration_error': ce}


def _slice_metrics(model, pairs):
    pairs = list(pairs)
    training_rows = [tr for tr, _ in pairs]
    model_metrics = evaluate(model, training_rows).__dict__ if training_rows else {
        'n': 0, 'log_loss': None, 'brier': None, 'accuracy': None, 'calibration_error': None,
    }
    market_probs = [_market_red_probability(raw) for _, raw in pairs]
    ys = [tr.y_a_win for tr, _ in pairs]
    return {'model': model_metrics, 'market_no_vig': _probability_metrics(market_probs, ys)}


def _experience(row, side):
    return f(row, f'{side}_wins') + f(row, f'{side}_losses') + f(row, f'{side}_draw')


def _promotion_evidence(model, holdout_pairs, contract, *, source_url, last_date):
    slices = {
        'all': _slice_metrics(model, holdout_pairs),
        'ufc_debut_any': _slice_metrics(model, (p for p in holdout_pairs if min(_experience(p[1], 'r'), _experience(p[1], 'b')) == 0)),
        'low_experience_any_le2': _slice_metrics(model, (p for p in holdout_pairs if min(_experience(p[1], 'r'), _experience(p[1], 'b')) <= 2)),
        'male': _slice_metrics(model, (p for p in holdout_pairs if str(p[1].get('gender') or '').upper() == 'MALE')),
        'female': _slice_metrics(model, (p for p in holdout_pairs if str(p[1].get('gender') or '').upper() == 'FEMALE')),
        'three_round': _slice_metrics(model, (p for p in holdout_pairs if int(f(p[1], 'no_of_rounds')) == 3)),
        'five_round': _slice_metrics(model, (p for p in holdout_pairs if int(f(p[1], 'no_of_rounds')) == 5)),
        'market_red_favorite': _slice_metrics(model, (p for p in holdout_pairs if (_market_red_probability(p[1]) or 0.5) >= 0.5)),
        'market_red_underdog': _slice_metrics(model, (p for p in holdout_pairs if (_market_red_probability(p[1]) or 0.5) < 0.5)),
    }
    weight_classes = sorted({str(raw.get('weight_class') or '') for _, raw in holdout_pairs if raw.get('weight_class')})
    slices['weight_class'] = {
        wc: _slice_metrics(model, (p for p in holdout_pairs if str(p[1].get('weight_class') or '') == wc))
        for wc in weight_classes
    }

    blockers = []
    all_model = slices['all']['model']
    all_market = slices['all']['market_no_vig']
    debut = slices['ufc_debut_any']['model']
    if int(all_model.get('n') or 0) < int(contract['holdout_n_min']):
        blockers.append('HOLDOUT_N_INSUFFICIENT')
    if int(debut.get('n') or 0) < int(contract['debut_n_min']):
        blockers.append('DEBUT_SLICE_N_INSUFFICIENT')
    if all_model.get('calibration_error') is None or float(all_model['calibration_error']) > float(contract['calibration_error_max']):
        blockers.append('CALIBRATION_ERROR_GATE')
    if all_market.get('brier') is None or all_model.get('brier') is None or float(all_model['brier']) > float(all_market['brier']) + float(contract['max_brier_delta_vs_market']):
        blockers.append('BRIER_VS_MARKET_GATE')
    if all_market.get('log_loss') is None or all_model.get('log_loss') is None or float(all_model['log_loss']) > float(all_market['log_loss']) + float(contract['max_log_loss_delta_vs_market']):
        blockers.append('LOG_LOSS_VS_MARKET_GATE')

    last_training_day = datetime.strptime(last_date, '%Y-%m-%d').date()
    evaluated_day = datetime.now(timezone.utc).date()
    training_age_days = max(0, (evaluated_day - last_training_day).days)
    if training_age_days > int(contract['training_data_max_age_days']):
        blockers.append('TRAINING_DATA_STALE')

    # TidyTuesday documents these fields only as moneyline betting odds. It does not
    # establish that they are point-in-time closing prices, so this cannot satisfy
    # SportsEdge's closing-no-vig promotion requirement by itself.
    closing_baseline_verified = False
    if contract.get('closing_market_provenance_required', True) and not closing_baseline_verified:
        blockers.append('CLOSING_ODDS_PROVENANCE_UNVERIFIED')

    # The source does not expose a short-notice/late-replacement field, so that
    # required validation slice remains genuinely unrun instead of being inferred.
    short_notice_slice_available = False
    if contract.get('short_notice_slice_required', True) and not short_notice_slice_available:
        blockers.append('SHORT_NOTICE_SLICE_UNAVAILABLE')

    return {
        'schema_version': 1,
        'sport': 'UFC',
        'promoted': not blockers,
        'status': 'PROMOTED' if not blockers else 'UNVERIFIED',
        'blockers': blockers,
        'contract': contract,
        'training_source': source_url,
        'last_training_fight_date': last_date,
        'training_freshness': {
            'evaluated_at_utc_date': evaluated_day.isoformat(),
            'age_days': training_age_days,
            'max_age_days': int(contract['training_data_max_age_days']),
            'fresh': training_age_days <= int(contract['training_data_max_age_days']),
        },
        'market_baseline': {
            'source_fields': ['r_odds', 'b_odds'],
            'no_vig_normalization': True,
            'closing_baseline_verified': closing_baseline_verified,
            'provenance_note': 'Dataset documentation identifies moneyline odds but does not establish closing-price provenance.',
        },
        'short_notice_slice_available': short_notice_slice_available,
        'slices': slices,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default=DEFAULT_URL)
    ap.add_argument('--output', default='models/ufc_logistic_v1.json')
    ap.add_argument('--metrics', default='artifacts/ufc_training_metrics.json')
    ap.add_argument('--promotion-evidence', default='artifacts/ufc_promotion_evidence.json')
    ap.add_argument('--promotion-contract', default='config/ufc_promotion_contract_v1.json')
    a = ap.parse_args()

    req = Request(a.url, headers={'User-Agent': 'SportsEdge/1.0'})
    text = urlopen(req, timeout=60).read().decode('utf-8')
    rows = list(csv.DictReader(text.splitlines()))
    rows = [r for r in rows if r.get('winner') in {'Red', 'Blue'} and r.get('date')]
    rows.sort(key=lambda r: (r['date'], r.get('location', ''), r.get('r_fighter', ''), r.get('b_fighter', '')))

    elo = defaultdict(lambda: 1500.0)
    out = []
    for r in rows:
        rn, bn = r['r_fighter'], r['b_fighter']
        er, eb = elo[rn], elo[bn]
        recent_r = min(1.0, max(0.0, 0.5 + 0.08 * (f(r, 'r_current_win_streak') - f(r, 'r_current_lose_streak'))))
        recent_b = min(1.0, max(0.0, 0.5 + 0.08 * (f(r, 'b_current_win_streak') - f(r, 'b_current_lose_streak'))))
        features = {
            'elo_diff': er-eb,
            'age_diff': f(r, 'r_age')-f(r, 'b_age'),
            'reach_diff': (f(r, 'r_reach_cms')-f(r, 'b_reach_cms'))/2.54,
            'height_diff': (f(r, 'r_height_cms')-f(r, 'b_height_cms'))/2.54,
            'slpm_diff': f(r, 'r_avg_sig_str_landed')-f(r, 'b_avg_sig_str_landed'),
            'sapm_diff': 0.0,
            'str_acc_diff': f(r, 'r_avg_sig_str_pct')-f(r, 'b_avg_sig_str_pct'),
            'str_def_diff': 0.0,
            'td_avg_diff': f(r, 'r_avg_td_landed')-f(r, 'b_avg_td_landed'),
            'td_acc_diff': f(r, 'r_avg_td_pct')-f(r, 'b_avg_td_pct'),
            'td_def_diff': 0.0,
            'sub_avg_diff': f(r, 'r_avg_sub_att')-f(r, 'b_avg_sub_att'),
            'recent_win_rate_diff': recent_r-recent_b,
            'sos_diff': 0.0,
            'rest_days_diff': 0.0,
            'late_replacement_diff': 0.0,
            'experience_diff': (f(r, 'r_wins')+f(r, 'r_losses'))-(f(r, 'b_wins')+f(r, 'b_losses')),
        }
        y = 1 if r['winner'] == 'Red' else 0
        out.append(TrainingRow(r['date'], r.get('location', ''), rn, bn, y, features))
        elo[rn], elo[bn] = update_elo(er, eb, float(y))

    model, metrics = fit_chronological(out)
    n = len(out)
    train_end = max(1, int(n * 0.70))
    holdout_start = max(train_end + 1, int(n * 0.85))
    holdout_pairs = list(zip(out[holdout_start:], rows[holdout_start:]))
    contract = json.loads(Path(a.promotion_contract).read_text(encoding='utf-8'))
    promotion = _promotion_evidence(model, holdout_pairs, contract, source_url=a.url, last_date=rows[-1]['date'])

    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(a.promotion_evidence).parent.mkdir(parents=True, exist_ok=True)
    payload = model.as_dict()
    payload['training_source'] = a.url
    payload['training_rows'] = len(out)
    payload['last_training_fight_date'] = rows[-1]['date']
    payload['holdout_metrics'] = metrics.__dict__
    payload['promotion_status'] = promotion['status']
    Path(a.output).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    Path(a.metrics).write_text(json.dumps(metrics.__dict__, indent=2, sort_keys=True), encoding='utf-8')
    Path(a.promotion_evidence).write_text(json.dumps(promotion, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps({'rows': len(out), 'last_date': rows[-1]['date'], 'promotion_status': promotion['status'], 'promotion_blockers': promotion['blockers'], **metrics.__dict__}, sort_keys=True))


if __name__ == '__main__':
    main()
