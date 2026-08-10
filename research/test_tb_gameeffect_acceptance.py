#!/usr/bin/env python3
"""Reproduce TB shared-game-effect calibration using sigma inherited from Hits."""
import pickle, numpy as np, sys
sys.path.insert(0, '../foundation')
from sportsedge_shared_game_effect import SIGMA_GAME_EFFECT

d = pickle.load(open('tb_gameeffect_data.pkl', 'rb'))
dataset = d['dataset']; train_pa_pool = d['train_pa_pool']
train = [x for x in dataset if x['season'] in ('2021', '2022')]
holdout = [x for x in dataset if x['season'] in ('2023', '2024')]

LG_PH = 0.2258

def scaled(x, ah, ahr, kp):
    ch = (x['p_h']/LG_PH)**ah
    chr_ = (x['p_hr']/0.03357)**ahr
    pk = x['park']**kp
    return np.array([x['rates']['s']*ch, x['rates']['d']*ch, x['rates']['t']*ch, x['rates']['hr']*chr_*pk])

AH, AHR, KP = 0.7, 0.3, 0.5
tr_pa = np.array([x['actual_pa'] for x in train], dtype=float)
tr_tb = np.array([x['actual_tb'] for x in train], dtype=float)
R = np.array([scaled(x, AH, AHR, KP) for x in train])
SC = tr_tb.sum() / ((R*np.array([1,2,3,4])).sum(axis=1) * tr_pa).sum()

rng = np.random.default_rng(seed=3100); N_SIM = 2000; SHRINK = 5
MAXPA = int(max(train_pa_pool.max(), max(g['actual_pa'] for g in holdout))) + 2
thr = [0.5, 1.5, 2.5]; sp = {t: [] for t in thr}; ac = {t: [] for t in thr}

for g in holdout:
    pool = np.array(g['pa_pool']); n = len(pool); wt = n/(n+SHRINK)
    use = rng.random(N_SIM) < wt; draws = np.empty(N_SIM, dtype=int); n1 = use.sum()
    if n1: draws[use] = rng.choice(pool, size=n1, replace=True)
    if N_SIM-n1: draws[~use] = rng.choice(train_pa_pool, size=N_SIM-n1, replace=True)
    ps = np.clip(scaled(g, AH, AHR, KP) * SC, 1e-5, 0.5)
    gfac = rng.lognormal(-0.5*SIGMA_GAME_EFFECT**2, SIGMA_GAME_EFFECT, N_SIM)
    u = rng.random((N_SIM, MAXPA))
    scaled_ps = ps[None,:] * gfac[:,None]
    cum = np.cumsum(scaled_ps, axis=1)
    val = np.zeros((N_SIM, MAXPA), dtype=np.int8)
    val[u < cum[:,3:4]] = 4; val[u < cum[:,2:3]] = 3
    val[u < cum[:,1:2]] = 2; val[u < cum[:,0:1]] = 1
    mask = np.arange(MAXPA)[None,:] < draws[:,None]
    tb = (val*mask).sum(axis=1)
    for t in thr:
        sp[t].append((tb>t).mean()); ac[t].append(1 if g['actual_tb']>t else 0)

print(f'TB via packaged sigma={SIGMA_GAME_EFFECT} (inherited from Hits, not refit)')
worst = 0
for t in thr:
    s=np.array(sp[t]); a=np.array(ac[t])
    gap=abs(s.mean()-a.mean())*100; se=np.sqrt(a.mean()*(1-a.mean())/len(a))*100
    worst=max(worst,gap/se)
    print(f'  {t}: sim={s.mean():.4f} act={a.mean():.4f} gap={gap:.2f}pp ({gap/se:.2f} SE)')
print(f'WORST: {worst:.2f} SE (original result: 1.60 SE)')
assert abs(worst-1.60) < 0.20, f'FAILED to reproduce: got {worst:.2f}'
print('PASS')
