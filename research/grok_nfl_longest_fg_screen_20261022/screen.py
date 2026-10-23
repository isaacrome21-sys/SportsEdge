"""SCREEN: NFL longest FG made (NFL_LONGEST_FG_EMPIRICAL), point-in-time,
out-of-sample by season 2019-2025 (REG kicker-games).  Inputs: hashed
nflverse pbp 2018-2025 + nfldata games.csv (see the game-scoring branch
SOURCES.json for URLs/hashes; re-hashed in this run's output).
Model input = only that kicker's games with kickoff strictly before.
Outcome at line L: kicker's longest MADE FG > L (a game with no made FG
counts as NOT over -- settlement of that case on DK is unverified).
Baseline: share of kicker-games in strictly earlier seasons with
longest made FG > L (add-one smoothed).  Lines declared a priori:
40.5, 44.5, 47.5, 50.5.  Label SCREEN; no market leg."""
import hashlib, json, math, random, sys
from collections import Counter, defaultdict
import pandas as pd
from sportsedge import nfl_kicking_empirical as k
from sportsedge import nfl_longest_fg_empirical as L

d = sys.argv[1]
LINES = (40.5, 44.5, 47.5, 50.5)
games = pd.read_csv(f"{d}/games.csv")
gtype = dict(zip(games.game_id, games.game_type))
pbp = pd.concat([pd.read_csv(f"{d}/pbp_{s}.csv.gz", usecols=list(k.PBP_COLUMNS), low_memory=False)
                 for s in range(2018, 2026)])
recs = k.build_kicking_games(pbp, games)
by_k = defaultdict(list)
for r in recs:
    by_k[r["kicker_id"]].append(r)

def longest(r):
    m = [x for x, ok in r["fg_attempts"] if ok]
    return max(m) if m else None

def season(r): return int(r["game_id"][:4])
def ll(p): return -math.log(min(max(p, 1e-12), 1 - 1e-12))

res = {ln: {"m": [], "b": [], "s": [], "p": [], "y": []} for ln in LINES}
refused = Counter()
for S in range(2019, 2026):
    prior = [r for r in recs if season(r) < S]
    base = {ln: (sum(1 for r in prior if (longest(r) or 0) > ln) + 1) / (len(prior) + 2) for ln in LINES}
    for r in recs:
        if season(r) != S or gtype.get(r["game_id"]) != "REG":
            continue
        lg = longest(r)
        for ln in LINES:
            try:
                p = L.price_longest_fg(by_k[r["kicker_id"]], kicker_id=r["kicker_id"],
                                       kickoff=r["kickoff"], line=ln)["p_made_longer_than_line"]
            except L.NflLongestFgError as e:
                refused[str(e).split(":")[0] + ":" + str(e).split(":")[1] if ":" in str(e) else str(e)] += 1
                continue
            y = (lg or 0) > ln
            R = res[ln]
            R["m"].append(ll(p if y else 1 - p)); R["b"].append(ll(base[ln] if y else 1 - base[ln]))
            R["s"].append(S); R["p"].append(p); R["y"].append(y)

rng = random.Random(20261022)
out = {"label": "SCREEN", "engine": L.ENGINE_VERSION,
       "baseline": "earlier-seasons share of kicker-games with longest made FG > line",
       "metric": "mean binary log loss (lower better); delta = model - baseline",
       "outcome_rule": "no made FG counts as not-over (DK settlement unverified)",
       "inputs_sha256": {f: hashlib.sha256(open(f"{d}/{f}", "rb").read()).hexdigest()
                         for f in ["games.csv"] + [f"pbp_{s}.csv.gz" for s in range(2018, 2026)]},
       "kicker_games_built": len(recs), "refused_row_lines": dict(refused), "lines": {}}
for ln, R in res.items():
    dm = [a - b for a, b in zip(R["m"], R["b"])]
    n = len(dm)
    boots = sorted(sum(dm[rng.randrange(n)] for _ in range(n)) / n for _ in range(1000))
    per = {s: round(sum(v for v, ss in zip(dm, R["s"]) if ss == s) / max(1, R["s"].count(s)), 5)
           for s in sorted(set(R["s"]))}
    # calibration by model-probability decile
    pairs = sorted(zip(R["p"], R["y"]))
    cal = []
    for i in range(5):
        c = pairs[i * n // 5:(i + 1) * n // 5]
        cal.append([round(sum(p for p, _ in c) / len(c), 4), round(sum(y for _, y in c) / len(c), 4), len(c)])
    out["lines"][str(ln)] = {
        "n": n, "base_rate_observed": round(sum(R["y"]) / n, 4),
        "model_ll": round(sum(R["m"]) / n, 5), "base_ll": round(sum(R["b"]) / n, 5),
        "delta": round(sum(dm) / n, 5), "ci95": [round(boots[25], 5), round(boots[974], 5)],
        "seasons_model_better": sum(v < 0 for v in per.values()), "per_season_delta": per,
        "calibration_quintiles_[mean_p,obs_rate,n]": cal,
        "verdict": "SCREEN_BEATS_NAIVE" if boots[974] < 0 else (
            "SCREEN_WORSE_THAN_NAIVE" if boots[25] > 0 else "SCREEN_INCONCLUSIVE")}
print(json.dumps(out, indent=1))
