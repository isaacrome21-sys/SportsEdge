#!/usr/bin/env python3
"""Independent hand check (prereg §7): recompute LEVEL v2 total means
from the raw corpus WITHOUT importing the candidate module, and compare
to the evaluator's audit CSV (< 1e-9). Also a no-lookahead teeth check:
corrupting every game at/after a fixture's kickoff must not move it."""
import csv, random, sys
from datetime import datetime
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")

def load(path):
    out = []
    for r in csv.DictReader(open(path)):
        if r["game_type"] != "REG" or not (2017 <= int(r["season"]) <= 2025):
            continue
        if r["home_score"] == "" or r["away_score"] == "":
            continue
        k = datetime.fromisoformat(f"{r['gameday']}T{r['gametime'] or '00:00'}").replace(tzinfo=ET)
        out.append(dict(k=k, s=int(r["season"]), h=r["home_team"], a=r["away_team"],
                        hs=int(r["home_score"]), as_=int(r["away_score"])))
    return out

def lvl(games, kick, season):
    # newest-first walk, explicit ages
    prior = sorted([g for g in games if g["k"] < kick and g["s"] in (season-1, season)],
                   key=lambda g: (g["k"], g["a"], g["h"]), reverse=True)
    if not prior: return 22.0, prior
    num = den = 0.0
    for age, g in enumerate(prior):
        w = 2.0 ** (-age / 128.0); num += w * (g["hs"] + g["as_"]) / 2.0; den += w
    return num / den, prior

def mean_for(games, fx):
    L, prior = lvl(games, fx["k"], fx["s"])
    def res(team):
        mine = [g for g in prior if team in (g["h"], g["a"])]   # newest first
        so = sd = sw = 0.0
        for age, g in enumerate(mine):
            anchor, _ = lvl(games, g["k"], g["s"])
            pf, pa = (g["hs"], g["as_"]) if g["h"] == team else (g["as_"], g["hs"])
            w = 2.0 ** (-age / 6.0) * (0.5 if g["s"] < fx["s"] else 1.0)
            so += w * (pf - anchor); sd += w * (pa - anchor); sw += w
        return so / (sw + 3.0), sd / (sw + 3.0)
    ho, hd = res(fx["h"]); ao, ad = res(fx["a"])
    return (L + (ho + ad) / 2 + 0.75) + (L + (ao + hd) / 2 - 0.75)

def main(corpus, audit):
    games = load(corpus)
    rows = list(csv.DictReader(open(audit)))
    rng = random.Random(20261017)
    picks = rng.sample(rows, 12) + [rows[0], rows[-1]]
    worst = 0.0
    for r in picks:
        k = datetime.fromisoformat(r["date"])
        fx = next(g for g in games if g["k"] == k and g["h"] == r["home"] and g["a"] == r["away"])
        m = mean_for(games, fx)
        worst = max(worst, abs(m - float(r["cand_total_mean"])))
        # teeth: corrupt everything at/after kickoff
        corrupt = [dict(g, hs=g["hs"] + 50) if g["k"] >= fx["k"] else g for g in games]
        assert abs(mean_for(corrupt, fx) - m) < 1e-12, "LOOKAHEAD"
        # control: corrupting a strictly-prior same-team game MUST move it
        prior_team = [g for g in games if g["k"] < fx["k"] and fx["h"] in (g["h"], g["a"])
                      and g["s"] in (fx["s"] - 1, fx["s"])]
        if prior_team:
            tgt = max(prior_team, key=lambda g: g["k"])
            ctl = [dict(g, hs=g["hs"] + 50) if g is tgt else g for g in games]
            assert abs(mean_for(ctl, fx) - m) > 1e-6, "CONTROL_DID_NOT_MOVE"
    print(f"HANDCHECK n={len(picks)} max_abs_diff={worst:.3e} (audit rounded to 1e-9)")
    print("NO_LOOKAHEAD teeth: PASS; prior-game control moves: PASS")
    return 0 if worst < 1e-8 else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
