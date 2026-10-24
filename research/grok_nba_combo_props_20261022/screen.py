"""SCREEN: NBA combo props (P+R, P+A, R+A) on the sportsdataverse ESPN
player box 2024-25 regular season (hashed in SOURCES.json).  Model =
nba_combo_prop_research (V1 construction); baseline = league
expanding climatology (V1 program's B2), both strictly PIT by date.
Metric: mean CRPS (lower better).  Calibration only; no market leg."""
import json, random, sys
from collections import defaultdict
import pandas as pd
from sportsedge import nba_prop_empirical as v1
from sportsedge import nba_combo_prop_research as C

df = pd.read_parquet(sys.argv[1])
df = df[df.season_type == 2]
recs = [{"player_id": str(r.athlete_id), "player_name": r.athlete_display_name,
         "position": r.athlete_position_abbreviation, "game_date": str(r.game_date)[:10],
         "game_id": str(r.game_id), "minutes": r.minutes, "points": r.points,
         "rebounds": r.rebounds, "assists": r.assists}
        for r in df.itertuples() if not r.did_not_play]
store = v1.GameLogStore(recs)
dates = sorted({g["game_date"] for g in store._league})
out = {"label": "SCREEN", "season": "2024-25 REG", "counters": store.counters, "families": {}}
rng = random.Random(20261022)
for combo in C.COMBOS:
    m_all, b_all = [], []
    by_date = defaultdict(list)
    for g in store._league:
        by_date[g["game_date"]].append(g)
    for d in dates:
        lg = [C.combo_value(g, combo) for g in store._league if g["game_date"] < d]
        if not lg:
            continue
        grp = defaultdict(list)
        for g in store._league:
            if g["game_date"] < d:
                grp[store._players[g["player_id"]]["group"]].append(C.combo_value(g, combo))
        lg_s, lg_p = v1._sorted_prefix(lg)
        for g in by_date[d]:
            pid = g["player_id"]
            pri = C._prior(store, pid, combo, d)
            if len(pri) < v1.MIN_PRIOR_GAMES:
                continue
            pool = grp[store._players[pid]["group"]]
            if len(pool) < v1.B1_MIN_POOL:
                pool = lg
            y = C.combo_value(g, combo)
            m_all.append(v1.MixtureDistribution(pri, pool).crps(y))
            b_all.append(v1.empirical_crps(lg_s, lg_p, y))
    dm = [a - b for a, b in zip(m_all, b_all)]
    n = len(dm)
    boots = sorted(sum(dm[rng.randrange(n)] for _ in range(n)) / n for _ in range(500))
    out["families"][combo] = {"n": n, "model_crps": round(sum(m_all) / n, 4),
        "baseline_crps": round(sum(b_all) / n, 4), "delta": round(sum(dm) / n, 4),
        "ci95": [round(boots[12], 4), round(boots[487], 4)],
        "verdict": "SCREEN_BEATS_CLIMATOLOGY" if boots[487] < 0 else "SCREEN_NOT_BEATING_CLIMATOLOGY"}
print(json.dumps(out, indent=1))
