"""Independent hand check for the anytime-TD calibration scorer.

Recomputes the 12 handcheck rows stored in the results JSON directly from
the raw pinned CSVs with standalone code — this file imports NOTHING from
atd_engine or the scorer — and compares model_p / pool_p / raw_p / outcome
to the scored values. Exits nonzero on any mismatch beyond 1e-9.

Usage: python3 handcheck_nfl_atd.py --data DIR --results results.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

FILES = ["ps_2018.csv.gz", "ps_2019.csv.gz", "ps_2020.csv.gz",
         "ps_2021.csv.gz", "ps_2022.csv.gz", "ps_2023.csv.gz",
         "ps_2024.csv.gz", "sp_2025.csv.gz"]
K_A, HALF_LIFE, MAX_EV, MIN_GAMES, POOL_MIN = 10.0, 8.0, 16, 4, 200


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--results", required=True)
    args = ap.parse_args()
    data = Path(args.data)
    # (pid) -> [(season, week, group, td)], plus season -> [(week, group, td)]
    mine: dict = {}
    by_season: dict = {}
    for name in FILES:
        with gzip.open(data / name, "rt") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG":
                    continue
                s, w = int(r["season"]), int(r["week"])
                td = 1 if num(r.get("rushing_tds")) + num(r.get("receiving_tds")) >= 1 else 0
                g = r.get("position_group") or ""
                mine.setdefault(r["player_id"], []).append((s, w, g, td))
                by_season.setdefault(s, []).append((w, g, td))
    for pid in mine:
        mine[pid].sort()

    results = json.loads(Path(args.results).read_text())
    bad = 0
    for row in results["handcheck_rows"]:
        s, w, pid = row["season"], row["week"], row["pid"]
        ev = [a for a in mine.get(pid, [])
              if a[0] >= s - 1 and (a[0], a[1]) < (s, w)]
        ev.sort(reverse=True)
        ev = ev[:MAX_EV]
        assert len(ev) >= MIN_GAMES, f"gate mismatch for {pid}"
        group = ev[0][2]
        cur = [t for (wk, g, t) in by_season.get(s, []) if wk < w and g == group]
        if len(cur) >= POOL_MIN:
            pool = sum(cur) / len(cur)
        else:
            prev = [t for (wk, g, t) in by_season.get(s - 1, []) if g == group]
            pool = sum(prev) / len(prev)
        ws = [0.5 ** (i / HALF_LIFE) for i in range(len(ev))]
        t_w = sum(wi * a[3] for wi, a in zip(ws, ev))
        n_w = sum(ws)
        model_p = (t_w + K_A * pool) / (n_w + K_A)
        raw_p = sum(a[3] for a in ev) / len(ev)
        # outcome: the player's own row at (s, w)
        own = [a for a in mine[pid] if a[0] == s and a[1] == w]
        y = own[0][3] if own else None
        for label, got, want in (("model_p", model_p, row["model_p"]),
                                 ("pool_p", pool, row["pool_p"]),
                                 ("raw_p", raw_p, row["raw_p"]),
                                 ("y", y, row["y"])):
            if got is None or abs(got - want) > 1e-9:
                print(f"MISMATCH {label} pid={pid} s={s} w={w}: "
                      f"hand={got} scored={want}")
                bad += 1
    n = len(results["handcheck_rows"])
    print(f"handcheck: {n} rows recomputed independently, "
          f"{'ALL MATCH' if bad == 0 else f'{bad} MISMATCHES'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
