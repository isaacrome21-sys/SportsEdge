"""Build per-game period and team-count tables from hashed nflverse pbp (no network)."""
import csv, gzip, hashlib, json, sys
from collections import defaultdict
SRC = sys.argv[1]; OUT = sys.argv[2]
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
dates = {}
for r in csv.DictReader(open(f"{SRC}/games.csv")):
    dates[r["game_id"]] = r["gameday"]
period_rows, count_rows, sources = [], [], {"games.csv": sha(f"{SRC}/games.csv")}
def f(x):
    try: return float(x)
    except: return 0.0
for season in range(2018, 2026):
    p = f"{SRC}/pbp_{season}.csv.gz"; sources[f"pbp_{season}.csv.gz"] = sha(p)
    g = {}
    for r in csv.DictReader(gzip.open(p, "rt")):
        gid = r["game_id"]
        if r["season_type"] != "REG": continue
        G = g.setdefault(gid, {"home": r["home_team"], "away": r["away_team"], "week": int(r["week"]),
             "qend": {}, "final": (f(r["home_score"]), f(r["away_score"])),
             "c": defaultdict(float)})
        q = r["qtr"]
        if q and r["total_home_score"] != "":
            qi = int(float(q)); hs, as_ = f(r["total_home_score"]), f(r["total_away_score"])
            prev = G["qend"].get(qi, (0, 0)); G["qend"][qi] = (max(prev[0], hs), max(prev[1], as_))
        pos, de = r["posteam"], r["defteam"]
        if not pos or not de: continue
        c = G["c"]
        if r["field_goal_result"] == "made": c[(pos, "fg_made")] += 1
        if r["extra_point_result"] == "good": c[(pos, "xp_made")] += 1
        if r["sack"] == "1" or r["sack"] == "1.0": c[(de, "sacks")] += 1
        if r["interception"] in ("1", "1.0"): c[(pos, "turnovers")] += 1
        if r["fumble_lost"] in ("1", "1.0"): c[(pos, "turnovers")] += 1
    for gid, G in sorted(g.items()):
        h, a = G["home"], G["away"]
        if sorted(G["qend"])[:4] != [1, 2, 3, 4]: continue
        cum = [(0, 0)] + [G["qend"][i] for i in (1, 2, 3, 4)]
        row = {"game_id": gid, "season": season, "week": G["week"], "date": dates[gid], "home": h, "away": a}
        for i in (1, 2, 3, 4):
            row[f"q{i}_h"] = int(cum[i][0] - cum[i-1][0]); row[f"q{i}_a"] = int(cum[i][1] - cum[i-1][1])
        row["h1_h"] = int(cum[2][0]); row["h1_a"] = int(cum[2][1])
        row["h2_h"] = int(G["final"][0] - cum[2][0]); row["h2_a"] = int(G["final"][1] - cum[2][1])  # 2H includes OT
        period_rows.append(row)
        for t, o in ((h, a), (a, h)):
            cr = {"game_id": gid, "season": season, "date": dates[gid], "team": t, "opp": o, "home": int(t == h)}
            for k in ("fg_made", "xp_made", "sacks", "turnovers"): cr[k] = int(G["c"][(t, k)])
            count_rows.append(cr)
for name, rows in (("period_table.csv", period_rows), ("team_count_table.csv", count_rows)):
    with open(f"{OUT}/{name}", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)
    sources[name] = sha(f"{OUT}/{name}")
json.dump(sources, open(f"{OUT}/SOURCES.json", "w"), indent=1, sort_keys=True)
print(len(period_rows), len(count_rows))
