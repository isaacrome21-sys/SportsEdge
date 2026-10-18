"""Independent check (no evaluator import): PASS_YDS population size and mean B1 CRPS."""
import csv, gzip, glob, sys
from collections import defaultdict
d = defaultdict(lambda: defaultdict(list))
for p in sorted(glob.glob(sys.argv[1] + "/ps_*.csv.gz")) + sorted(glob.glob(sys.argv[1] + "/sp_*.csv.gz")):
    for r in csv.DictReader(gzip.open(p, "rt")):
        if r["season_type"] == "REG":
            d[int(r["season"])][r["player_id"]].append((int(r["week"]), r["position"], float(r["attempts"] or 0), float(r["passing_yards"] or 0)))
n = 0; tot = 0.0
for s in range(2020, 2026):
    for pid, g in d[s].items():
        g.sort()
        for i, (w, pos, att, y) in enumerate(g):
            pr = g[:i]
            if w < 4 or len(pr) < 3 or pos != "QB" or sum(x[2] for x in pr) / len(pr) < 20:
                continue
            vals = sorted(x[3] for x in pr)
            c = 0.0
            for k in range(-60, 701):
                F = sum(v <= k for v in vals) / len(vals)
                c += (F - (1.0 if y <= k else 0.0)) ** 2
            n += 1; tot += c
print(n, tot / n)
