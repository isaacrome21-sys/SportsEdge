"""Independent R1 recount (no repo imports): per-provider line coverage from the pinned
cfb_line_odds archive, written from the R1 rule text (school-keyed sides; spread mirror;
total agreement; ML sign cross-check vs a nonzero spread, unchecked pairs quarantined).
usage: r1_independent.py <cfb_line_odds.csv.gz> <first_season> <last_season>"""
import csv, gzip, sys, json, collections
path, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
G = collections.defaultdict(lambda: {"desc": None, "m": collections.defaultdict(lambda: collections.defaultdict(list))})
for r in csv.DictReader(gzip.open(path, "rt")):
    try: s = int(float(r["season"]))
    except ValueError: continue
    gid = (r["game_id"] or "").strip()
    if gid.endswith(".0"): gid = gid[:-2]
    book = (r["book"] or "").strip()
    if not (lo <= s <= hi) or not gid or not book: continue
    g = G[(book, gid)]
    if g["desc"] is None: g["desc"] = r["game_desc"] or ""
    g["m"][(r["market_type"] or "").strip()][(r["abbr"] or "").strip()].append(r)
def num(x, integer=False):
    x = (x or "").strip()
    if not x: return None
    v = float(x)
    if integer:
        return int(v) if v.is_integer() and v != 0 else None
    return v
cov = collections.defaultdict(collections.Counter)
for (book, gid), g in G.items():
    c = cov[book]; c["games_with_any_market"] += 1
    if "@" not in g["desc"]: continue
    away, home = [x.strip() for x in g["desc"].split("@", 1)]
    if not away or not home: continue
    m = g["m"]; sh = None
    if "spread" in m:
        hv = {num(r["lines"]) for r in m["spread"].get(home, [])} - {None}
        av = {num(r["lines"]) for r in m["spread"].get(away, [])} - {None}
        if len(hv) > 1 or len(av) > 1 or not hv or not av or abs(next(iter(hv)) + next(iter(av))) > 1e-9:
            c["spread_quarantined"] += 1
        else:
            sh = next(iter(hv)); c["spread_ok"] += 1
    if "total" in m:
        vals = {num(r["lines"]) for k in ("over", "under", "Over", "Under") for r in m["total"].get(k, [])} - {None}
        if len(vals) != 1: c["total_quarantined"] += 1
        else: c["total_ok"] += 1
    if "money_line" in m:
        hv = {num(r["odds"], True) for r in m["money_line"].get(home, [])} - {None}
        av = {num(r["odds"], True) for r in m["money_line"].get(away, [])} - {None}
        if len(hv) > 1 or len(av) > 1: c["moneyline_quarantined"] += 1
        elif hv and av:
            h, a = next(iter(hv)), next(iter(av))
            if not sh: c["moneyline_quarantined"] += 1
            else:
                fav, dog = (h, a) if sh < 0 else (a, h)
                if fav < 0 < dog: c["moneyline_ok"] += 1
                else: c["moneyline_quarantined"] += 1
print(json.dumps({b: dict(cov[b]) for b in ("Bovada", "ESPN Bet", "William Hill (New Jersey)", "DraftKings")}, sort_keys=True))
