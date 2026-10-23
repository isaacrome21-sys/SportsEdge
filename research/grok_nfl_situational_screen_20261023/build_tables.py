"""Build per-game situational table from hashed nflverse pbp (no network)."""
import csv, gzip, hashlib, json, sys
SRC, OUT = sys.argv[1], sys.argv[2]
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def f(x):
    try: return float(x)
    except ValueError: return None
dates = {r["game_id"]: r for r in csv.DictReader(open(f"{SRC}/games.csv"))}
sources = {"games.csv": sha(f"{SRC}/games.csv")}
rows = []
for season in range(2018, 2026):
    p = f"{SRC}/pbp_{season}.csv.gz"; sources[f"pbp_{season}.csv.gz"] = sha(p)
    g = {}
    for r in csv.DictReader(gzip.open(p, "rt")):
        if r["season_type"] != "REG": continue
        G = g.setdefault(r["game_id"], {"home": r["home_team"], "away": r["away_team"], "first": None,
             "lead": 0, "saf": {}, "dst": {}})
        hs, as_ = f(r["total_home_score"]), f(r["total_away_score"])
        if hs is not None and as_ is not None:
            if G["first"] is None and hs + as_ > 0:
                G["first"] = "H" if hs > as_ else "A" if as_ > hs else "TIE"
            G["lead"] = max(G["lead"], int(abs(hs - as_)))
        pos, de = r["posteam"], r["defteam"]
        if r["safety"] in ("1", "1.0") and de:
            G["saf"][de] = G["saf"].get(de, 0) + 1
        if r["touchdown"] in ("1", "1.0") and r["td_team"] and pos:
            if r["td_team"] != pos or r["kickoff_attempt"] in ("1", "1.0"):
                G["dst"][r["td_team"]] = G["dst"].get(r["td_team"], 0) + 1
    for gid, G in sorted(g.items()):
        meta = dates.get(gid)
        if meta is None or meta["home_score"] == "" or G["first"] == "TIE": continue
        h, a = G["home"], G["away"]
        rows.append({"game_id": gid, "season": season, "date": meta["gameday"], "home": h, "away": a,
                     "home_pts": int(float(meta["home_score"])), "away_pts": int(float(meta["away_score"])),
                     "first_score": G["first"] or "NONE", "largest_lead": G["lead"],
                     "safety_h": G["saf"].get(h, 0), "safety_a": G["saf"].get(a, 0),
                     "dst_td_h": G["dst"].get(h, 0), "dst_td_a": G["dst"].get(a, 0)})
with open(f"{OUT}/situational_table.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)
sources["situational_table.csv"] = sha(f"{OUT}/situational_table.csv")
json.dump(sources, open(f"{OUT}/SOURCES.json", "w"), indent=1, sort_keys=True)
print(len(rows))
