#!/usr/bin/env python3
"""
Rebuild bb_hits_data.pkl -- the fixture behind the hitter-hits shared
game-effect result (7.56 SE -> 2.63 SE).

Source data: 2021-2024 regular-season batting/pitching game logs
  /home/claude/batting/batting.csv
  /home/claude/pitching/pitching.csv
Plus the lineup/starter reference:
  SportsEdge_FG_Model_Ready_2021_2024.csv  (uploaded dataset)

What this builds, per batter-game:
  b_rate  -- shrunk rolling hit rate for the batter (own history, prior
             games only, date-boundary rule -- see prior[] construction)
  p_rate  -- shrunk rolling hit-rate-allowed for the OPPOSING starter
             (starts-only appearances, prior to this game)
  pa_pool -- the batter's own last-30 PA-per-START history, used to sample
             workload rather than assume a fixed PA count
  actual_h, actual_pa -- the real outcome, for scoring only

Shrinkage constants (unchanged from original build):
  SH_B = 100
  SH_P = 200
  LEAGUE_PH = 0.2258

Reproducibility note: train_pa MUST iterate sorted(started). Iterating the raw
Python set makes pickle byte order depend on PYTHONHASHSEED and breaks
hash-based artifact gates even when the data multiset is identical.
"""
import csv, pickle, hashlib
from collections import defaultdict, OrderedDict
import numpy as np

MODEL_READY_PATH = '/mnt/user-data/uploads/SportsEdge_FG_Model_Ready_2021_2024.csv'
BATTING_PATH = '/home/claude/batting/batting.csv'
PITCHING_PATH = '/home/claude/pitching/pitching.csv'
SEASONS = {'2021', '2022', '2023', '2024'}
SH_B = 100
SH_P = 200
LEAGUE_PH = 0.2258


def main():
    model_ready = {r['gid']: r for r in csv.DictReader(open(MODEL_READY_PATH))}
    started = set()
    for gid, mr in model_ready.items():
        for side in ('vis', 'home'):
            for bid in mr[f'{side}_lineup'].split('|'):
                started.add((gid, bid))

    brows = []
    with open(BATTING_PATH) as f:
        for row in csv.DictReader(f):
            if row['date'][:4] not in SEASONS or row.get('gametype') != 'regular':
                continue
            brows.append(row)

    pg = defaultdict(lambda: {'h': 0, 'pa': 0})
    meta = {}
    for r in brows:
        k = (r['gid'], r['id'])
        pg[k]['h'] += int(r['b_h'])
        pg[k]['pa'] += int(r['b_pa'])
        meta[k] = r['date']

    by_player = defaultdict(list)
    for (gid, pid), s in pg.items():
        by_player[pid].append((meta[(gid, pid)], gid, s))

    prior = {}
    for pid, glist in by_player.items():
        by_date = OrderedDict()
        for d, g, s in glist:
            by_date.setdefault(d, []).append((g, s))
        cum = {'h': 0, 'pa': 0, 'n_start': 0, 'pa_pool': []}
        for d in sorted(by_date):
            for g, s in by_date[d]:
                prior[(g, pid)] = {'h': cum['h'], 'pa': cum['pa'], 'n_start': cum['n_start'], 'pa_pool': list(cum['pa_pool'])}
            for g, s in by_date[d]:
                cum['h'] += s['h']; cum['pa'] += s['pa']
                if (g, pid) in started:
                    cum['n_start'] += 1; cum['pa_pool'].append(s['pa'])

    league_hit = sum(v['h'] for v in prior.values()) / max(sum(v['pa'] for v in prior.values()), 1)
    train_pa = np.array([
        pg[(g, b)]['pa'] for (g, b) in sorted(started)
        if meta.get((g, b), '')[:4] in ('2021', '2022') and pg[(g, b)]['pa'] > 0
    ])

    apps = []
    with open(PITCHING_PATH) as f:
        for row in csv.DictReader(f):
            if row['date'][:4] not in SEASONS or row.get('gametype') != 'regular':
                continue
            apps.append(row)
    by_p = defaultdict(list)
    for r in apps: by_p[r['id']].append(r)
    for p in by_p: by_p[p].sort(key=lambda r: (r['date'], int(r['number'])))
    p_prior = {}
    for pid, recs in by_p.items():
        st = {'h': 0, 'bfp': 0}
        for rec in recs:
            p_prior[(rec['gid'], pid)] = dict(st)
            if rec.get('p_gs') == '1':
                st['h'] += int(rec['p_h']); st['bfp'] += int(rec['p_bfp'])

    dataset = []
    for gid, mr in model_ready.items():
        for side in ('vis', 'home'):
            opp = mr['home_starter_id'] if side == 'vis' else mr['vis_starter_id']
            pst = p_prior.get((gid, opp))
            if pst is None or pst['bfp'] == 0: continue
            p_rate = (pst['h'] + LEAGUE_PH * SH_P) / (pst['bfp'] + SH_P)
            ids = mr[f'{side}_lineup'].split('|')
            if len(ids) != 9: continue
            for slot, bid in enumerate(ids, start=1):
                bst = prior.get((gid, bid))
                if bst is None or bst['n_start'] < 5: continue
                b_rate = (bst['h'] + league_hit * SH_B) / (bst['pa'] + SH_B)
                a = pg.get((gid, bid))
                if a is None or a['pa'] == 0: continue
                dataset.append({'season': mr['season'], 'b_rate': b_rate, 'p_rate': p_rate, 'pa_pool': bst['pa_pool'][-30:], 'actual_h': a['h'], 'actual_pa': a['pa']})

    out_path = 'bb_hits_data.pkl'
    with open(out_path, 'wb') as fh: pickle.dump({'dataset': dataset, 'train_pa': train_pa}, fh)
    h = hashlib.sha256(open(out_path, 'rb').read()).hexdigest()
    print(f'dataset rows: {len(dataset)}   train_pa pool: {len(train_pa)}')
    print(f'SHA-256: {h}')
    return h


if __name__ == '__main__':
    main()
