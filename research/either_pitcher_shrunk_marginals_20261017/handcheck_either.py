"""Independent hand check (prereg sec. 7): recompute CHALLENGER/B1/B2 either probs for 12 2026 pairs
from the raw bundle with plain Python (no evaluator import, no numpy), compare < 1e-9."""
import gzip, json, random, sys
from datetime import date
F = {"HA": "hits", "BB": "baseOnBalls", "ER": "earnedRuns"}
starts = []  # (date, pid, gamePk, isHome, gameType, stats)
for line in gzip.open(sys.argv[1], "rt"):
    r = json.loads(line); pid = int(r["url"].split("/people/")[1].split("/")[0])
    seen = set()
    for st in json.loads(r["body"]).get("stats", []):
        for sp in st.get("splits", []):
            s = sp["stat"]
            if int(s.get("gamesStarted", 0)) != 1 or sp["game"]["gamePk"] in seen: continue
            seen.add(sp["game"]["gamePk"])
            starts.append((date.fromisoformat(sp["date"]), pid, sp["game"]["gamePk"], sp.get("isHome"), sp.get("gameType"), s))
rows = {}
for line in gzip.open(sys.argv[2], "rt"):
    r = json.loads(line); rows[(r["game_pk"], r["stat"], r["form"], r["T"])] = r
by_game = {}
for t in starts:
    if t[4] == "R": by_game.setdefault(t[2], []).append(t)
def prior(pid, d): return [t[5] for t in starts if t[1] == pid and t[0] < d]
def dist(rows, f, smooth=None):
    c = [0.0] * 61
    for s in rows: c[min(int(s[f]), 60)] += 1
    return c
random.seed(7)
games = [g for g, v in by_game.items() if len(v) == 2 and all(len(prior(t[1], t[0])) >= 5 for t in v)]
print("eligible pairs", len(games))
checked = 0
for g in random.sample(sorted(games), 12):
    a, b = by_game[g]; d = a[0]
    for stat, f in F.items():
        L = dist([t[5] for t in starts if t[0] < d], f); nL = sum(L); L = [x / nL for x in L]
        def marg(t, arm):
            c = dist(prior(t[1], d), f); n = sum(c)
            return {"C": [(c[v] + 10 * L[v]) / (n + 10) for v in range(61)], "B1": [x / n for x in c], "B2": L}[arm]
        for arm in ("C", "B1", "B2"):
            pa, pb = marg(a, arm), marg(b, arm)
            for (form, T), r in [((k[2], k[3]), v) for k, v in rows.items() if k[0] == g and k[1] == stat]:
                if form == "XPLUS": e = 1 - (1 - sum(pa[T:])) * (1 - sum(pb[T:]))
                else: e = 1 - (1 - sum(pa[:T + 1])) * (1 - sum(pb[:T + 1]))
                key = {"C": "CHALLENGER", "B1": "B1", "B2": "B2"}[arm]
                assert abs(e - r[key]) < 1e-9, (g, stat, form, T, arm, e, r[key])
                checked += 1
assert checked > 0
print("HANDCHECK_PASS cells", checked, "max tol 1e-9")
