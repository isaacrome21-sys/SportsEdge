#!/usr/bin/env python3
"""Acceptance test for packaged rolling-recalibration pitcher walks.

Development/shrinkage selection is 2023-only. Clean scoring is 2024-only.
This is research acceptance evidence; production capability must remain
unattested until the live runtime actually calls the rolling recalibration.
"""
import pickle, sys
import numpy as np
sys.path.insert(0, 'foundation')
from sportsedge_rolling_recal import SHRINKAGE

FIXTURE = 'bb_rolling_recal_dataset.pkl'
THRESHOLDS = [0.5, 1.5, 2.5, 3.5]
N_SIM = 2500
POOL_SHRINK = 5


def score(rows, train_pool):
    rng = np.random.default_rng(seed=5000)
    sp = {t: [] for t in THRESHOLDS}
    ac = {t: [] for t in THRESHOLDS}
    for g in rows:
        pool = np.array(g['pool'])
        n = len(pool)
        wt = n / (n + POOL_SHRINK)
        use = rng.random(N_SIM) < wt
        draws = np.empty(N_SIM, dtype=int)
        n1 = use.sum()
        if n1:
            draws[use] = rng.choice(pool, size=n1, replace=True)
        if N_SIM - n1:
            draws[~use] = rng.choice(train_pool, size=N_SIM-n1, replace=True)
        bd = rng.binomial(draws, g['recalibrated_rate'])
        for t in THRESHOLDS:
            sp[t].append((bd > t).mean())
            ac[t].append(1 if g['actual_bb'] > t else 0)
    worst = 0.0
    for t in THRESHOLDS:
        s = np.array(sp[t]); a = np.array(ac[t])
        gap = abs(s.mean() - a.mean()) * 100
        se = np.sqrt(a.mean() * (1-a.mean()) / len(a)) * 100
        z = gap / se
        worst = max(worst, z)
        print(f'{t}: sim={s.mean():.4f} act={a.mean():.4f} gap={gap:.2f}pp ({z:.2f} SE)')
    return worst


def main():
    d = pickle.load(open(FIXTURE, 'rb'))
    dataset = d['dataset']; train_pool = d['train_pool']
    test = [x for x in dataset if x['season'] == '2024']
    print(f'SHRINKAGE={SHRINKAGE}; clean test rows={len(test)}')
    worst = score(test, train_pool)
    print(f'WORST={worst:.2f} SE (reference 2.18 SE)')
    assert abs(worst - 2.18) < 0.30, f'FAILED to reproduce: {worst:.2f}'
    print('PASS')


if __name__ == '__main__':
    main()
