#!/usr/bin/env python3
"""Rebuild the Total Bases shared-game-effect acceptance fixture.

Sigma=0.20 is inherited from the Hits model and is not refit here. Dataset
construction intentionally avoids iterating unordered sets into serialized
array/list order. Determinism must still be verified by an external
independent-process rebuild check that compares SHA-256 outputs; this script
itself performs one build per invocation and does not claim otherwise.
"""
import csv, pickle, hashlib
import numpy as np

MODEL_READY_PATH = '/mnt/user-data/uploads/SportsEdge_FG_Model_Ready_2021_2024.csv'
INPUTS_PATH = '/mnt/user-data/uploads/SportsEdge_FG_Inputs_2021_2024.csv'
TB_COMPONENTS_PATH = 'tb_components.pkl'
HR_COMPONENTS_PATH = 'hr_components.pkl'
LG_PH = 0.2258
SH = 300


def build_dataset():
    c = pickle.load(open(TB_COMPONENTS_PATH, 'rb'))
    prior_b, prior_p, LG, pgm = c['prior_b'], c['prior_p'], c['LG'], c['pgm']
    model_ready = {r['gid']: r for r in csv.DictReader(open(MODEL_READY_PATH))}
    inputs = {r['gid']: r for r in csv.DictReader(open(INPUTS_PATH))}
    park_factor = pickle.load(open(HR_COMPONENTS_PATH, 'rb'))['park_factor']

    dataset = []
    for gid, mr in model_ready.items():
        inp = inputs.get(gid)
        if inp is None:
            continue
        pf = park_factor.get(inp['site'], 1.0)
        for side in ('vis', 'home'):
            opp = mr['home_starter_id'] if side == 'vis' else mr['vis_starter_id']
            pst = prior_p.get((gid, opp))
            if pst is None or pst['bfp'] < 100:
                continue
            p_h = (pst['h'] + LG_PH * 400) / (pst['bfp'] + 400)
            p_hr = (pst['hr'] + LG['hr'] * 400) / (pst['bfp'] + 400)
            for bid in mr[f'{side}_lineup'].split('|'):
                bst = prior_b.get((gid, bid))
                if bst is None or bst['n_start'] < 10 or bst['pa'] < 100:
                    continue
                rates = {k: (bst[k] + LG[k] * SH) / (bst['pa'] + SH) for k in ('s', 'd', 't', 'hr')}
                a = pgm.get((gid, bid))
                if a is None or a['pa'] == 0:
                    continue
                dataset.append({
                    'season': mr['season'], 'rates': rates, 'p_h': p_h, 'p_hr': p_hr,
                    'park': pf, 'pa_pool': bst['pa_pool'][-30:],
                    'actual_tb': a['s'] + 2 * a['d'] + 3 * a['t'] + 4 * a['hr'],
                    'actual_pa': a['pa'],
                })
    return dataset


def main():
    dataset = build_dataset()
    train = [x for x in dataset if x['season'] in ('2021', '2022')]
    holdout = [x for x in dataset if x['season'] in ('2023', '2024')]
    out_path = 'tb_gameeffect_data.pkl'
    payload = {'dataset': dataset, 'train_pa_pool': np.array([x['actual_pa'] for x in train])}
    with open(out_path, 'wb') as fh:
        pickle.dump(payload, fh)
    with open(out_path, 'rb') as fh:
        h = hashlib.sha256(fh.read()).hexdigest()
    print(f'dataset rows: {len(dataset)}  train: {len(train)}  holdout: {len(holdout)}')
    print(f'wrote {out_path}')
    print(f'SHA-256: {h}')
    return h


if __name__ == '__main__':
    main()
