"""Parity reproduction: score the frozen Oct 17 ESPN snapshot with the
engine module's own construction and compare against the two programs'
published calibration figures.

Programs reproduced:
* Oct 17 (B5/B6/B7): results/nba_props_calibration.json in the lane dir
  (points / rebounds / assists), spec SHA-256 47dc1314....
* Oct 18 extension (B8): results/nba_extension_results.json in the
  backtest_everything_20261018 dir (pra; points/rebounds/assists were
  re-scored there as a parity check and are compared too).

The predictive distributions and CRPS values are computed by
``sportsedge.nba_prop_empirical`` (MixtureDistribution + the module's
pool helpers). Per-date pool snapshots (sort / prefix sums) use numpy
exactly as the programs did; the engine's pure-Python pool helpers are
cross-checked against those numpy forms below. Per-game candidate
CRPS is additionally compared row-by-row against both programs'
scored-games CSVs.

Run:  python3 parity_reproduction.py [--snapshot LANE_DIR]
Writes parity_results.json next to this script. Exit code 0 iff the
scored population matches exactly (n=16,818) and every published mean
CRPS is reproduced within 1e-9.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from sportsedge.nba_prop_empirical import (  # noqa: E402
    B1_MIN_POOL, GameLogStore, MIN_PRIOR_GAMES, MixtureDistribution,
    empirical_crps, pool_ex_abs as eng_pool_ex_abs, pool_exx as eng_pool_exx,
    stat_value,
)
from sportsedge.sports.nba.nba_gamelog_decode import (  # noqa: E402
    NBAGamelogSchemaError, decode_nba_gamelog_event, iter_gamelog_games,
)

STATS = ["points", "rebounds", "assists", "pra"]
MIN_TOTAL = 20  # the programs' scored-population criterion (scoring only)
BOOT_N = 2000
SEED = 20261017
DEFAULT_SNAPSHOT = os.path.expanduser(
    "~/workspace/sportsedge/backtest_program_20261017/lanes/nba")
DEFAULT_EXTENSION = os.path.expanduser(
    "~/workspace/sportsedge/backtest_everything_20261018/results/"
    "nba_extension_results.json")
DEFAULT_EXTENSION_CSV = os.path.expanduser(
    "~/workspace/sportsedge/backtest_everything_20261018/results/"
    "nba_extension_scored_games.csv")


# ---------- numpy pool snapshots (the programs' exact forms) ----------------

def np_pool_ex_abs(sorted_vals, prefix, y):
    m = len(sorted_vals)
    if m == 0:
        return None
    k = int(np.searchsorted(sorted_vals, y, side="right"))
    left_sum = prefix[k]
    total = prefix[m]
    return (y * k - left_sum + (total - left_sum) - y * (m - k)) / m


def np_pool_exx(sorted_vals, prefix):
    m = len(sorted_vals)
    if m == 0:
        return None
    idx = np.arange(m)
    s = (sorted_vals * idx - prefix[idx]
         + (prefix[m] - prefix[idx + 1]) - sorted_vals * (m - idx - 1))
    return float(s.sum() / (m * m))


def snapshot(vals):
    arr = np.sort(np.array(vals, dtype=float)) if vals else np.array([])
    prefix = np.concatenate([[0.0], np.cumsum(arr)])
    exx = np_pool_exx(arr, prefix) if len(arr) else None
    return arr, prefix, exx


# ---------- checks -----------------------------------------------------------

def unit_checks():
    """The programs' own brute-force CRPS check, run against the engine,
    plus engine-vs-numpy pool-helper cross-checks."""
    rng = np.random.default_rng(7)
    worst = 0.0
    for _ in range(200):
        prior = rng.integers(0, 30, size=int(rng.integers(10, 25))).astype(float)
        pool = rng.integers(0, 30, size=int(rng.integers(30, 60))).astype(float)
        y = float(rng.integers(0, 30))
        dist = MixtureDistribution(list(prior), list(pool))
        got = dist.crps(y)
        n = len(prior)
        a = n / (n + 5.0)
        b = 5.0 / (n + 5.0)
        vals = np.concatenate([prior, pool])
        w = np.concatenate([np.full(n, a / n), np.full(len(pool), b / len(pool))])
        ey = float(np.sum(w * np.abs(vals - y)))
        exx = float(np.sum(w[:, None] * w[None, :] *
                           np.abs(vals[:, None] - vals[None, :])))
        want = ey - 0.5 * exx
        worst = max(worst, abs(got - want))
        assert abs(got - want) < 1e-9, (got, want)
    pool_worst = 0.0
    for _ in range(50):
        pool = rng.integers(0, 40, size=int(rng.integers(30, 500))).astype(float)
        arr, prefix, exx = snapshot(list(pool))
        svals = sorted(float(v) for v in pool)
        sprefix = [0.0]
        for v in svals:
            sprefix.append(sprefix[-1] + v)
        d1 = abs(eng_pool_exx(svals, sprefix) - exx)
        y = float(rng.integers(0, 40))
        d2 = abs(eng_pool_ex_abs(svals, sprefix, y)
                 - np_pool_ex_abs(arr, prefix, y))
        d3 = abs(empirical_crps(svals, sprefix, y)
                 - (np_pool_ex_abs(arr, prefix, y) - 0.5 * exx))
        pool_worst = max(pool_worst, d1, d2, d3)
        assert max(d1, d2, d3) < 1e-9, (d1, d2, d3)
    return {"brute_force_crps_max_abs_delta": worst,
            "engine_vs_numpy_pool_helpers_max_abs_delta": pool_worst}


# ---------- snapshot loading (the programs' rules, repo decoder) -------------

def load_records(snapshot_dir):
    data = os.path.join(snapshot_dir, "data")
    with open(os.path.join(data, "athletes.json")) as f:
        athletes = json.load(f)
    counters = {"athletes_enumerated": len(athletes), "decode_failures": 0}
    records = []
    for aid, info in athletes.items():
        path = os.path.join(data, "gamelogs", f"{aid}.json")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            payload = json.load(f)
        try:
            rows = list(iter_gamelog_games(payload))
        except NBAGamelogSchemaError:
            counters["decode_failures"] += 1
            continue
        for st_display, meta, cat_event in rows:
            if "regular season" not in str(st_display).lower():
                continue
            try:
                stats = decode_nba_gamelog_event(payload, cat_event)
                gdate = datetime.fromisoformat(
                    str(meta.get("gameDate")).replace("Z", "+00:00")).date()
            except (NBAGamelogSchemaError, ValueError, TypeError, KeyError):
                counters["decode_failures"] += 1
                continue
            records.append({
                "player_id": str(aid),
                "player_name": info.get("name"),
                "position": info.get("position_abbr"),
                "game_date": gdate,
                "game_id": str(cat_event.get("eventId")),
                "minutes": float(stats["minutes"]),
                "points": float(stats["points"]),
                "rebounds": float(stats["rebounds"]),
                "assists": float(stats["assists"]),
            })
    return athletes, records, counters


# ---------- scoring (the programs' loop; engine distributions) ---------------

def score(store, athletes):
    by_date = defaultdict(list)
    for aid in athletes:  # athletes.json order, as the programs iterated
        if aid not in store._players:
            continue
        for g in store._players[aid]["games"]:
            by_date[g["game_date"]].append((aid, g))
    dates_sorted = sorted(by_date)
    player_prior = {aid: [] for aid in store._players}
    pool_b2 = {s: [] for s in STATS}
    pool_b1 = {gname: {s: [] for s in STATS}
               for gname in ("Guard", "Forward", "Center")}
    scored = []
    fallback = 0
    for d in dates_sorted:
        snap = {}
        for s in STATS:
            snap[("B2", s)] = snapshot(pool_b2[s])
            for gname in pool_b1:
                snap[(gname, s)] = snapshot(pool_b1[gname][s])
        for aid, game in by_date[d]:
            group = store.position_group_of(aid)
            prior = player_prior[aid]
            if (len(prior) >= MIN_PRIOR_GAMES
                    and store.player_total_games(aid) >= MIN_TOTAL):
                row = {"date": d.isoformat(), "player_id": aid,
                       "group": group, "n_prior": len(prior)}
                for s in STATS:
                    y = stat_value(game, s)
                    b2_arr, b2_pre, b2_exx = snap[("B2", s)]
                    g_arr, g_pre, g_exx = snap[(group, s)]
                    if len(g_arr) >= B1_MIN_POOL:
                        b1 = (g_arr, g_pre, g_exx)
                        used_fallback = False
                    else:
                        b1 = (b2_arr, b2_pre, b2_exx)
                        used_fallback = True
                    if s == STATS[0]:
                        fallback += int(used_fallback)
                    prior_vals = [stat_value(pg, s) for pg in prior]
                    dist = MixtureDistribution.from_precomputed(
                        prior_vals, list(b1[0]), list(b1[1]), b1[2])
                    row[f"crps_cand_{s}"] = dist.crps(y)
                    row[f"crps_b1_{s}"] = np_pool_ex_abs(
                        b1[0], b1[1], y) - 0.5 * b1[2]
                    row[f"crps_b2_{s}"] = np_pool_ex_abs(
                        b2_arr, b2_pre, y) - 0.5 * b2_exx
                    row[f"actual_{s}"] = y
                scored.append(row)
        for aid, game in by_date[d]:
            group = store.position_group_of(aid)
            player_prior[aid].append(game)
            for s in STATS:
                v = stat_value(game, s)
                pool_b2[s].append(v)
                pool_b1[group][s].append(v)
    return scored, fallback, dates_sorted


def bootstrap(scored):
    """One rng stream, stats in program order (points, rebounds,
    assists, pra) — the extension's declared consumption order."""
    rng = np.random.default_rng(SEED)
    out = {}
    for s in STATS:
        d1 = np.array([r[f"crps_cand_{s}"] - r[f"crps_b1_{s}"] for r in scored])
        d2 = np.array([r[f"crps_cand_{s}"] - r[f"crps_b2_{s}"] for r in scored])
        blocks = defaultdict(lambda: [0.0, 0.0, 0])
        for r, a1, a2 in zip(scored, d1, d2):
            dt = datetime.fromisoformat(r["date"]).date()
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
            blocks[key][0] += a1
            blocks[key][1] += a2
            blocks[key][2] += 1
        keys = sorted(blocks)
        bs = np.array([blocks[k][0] for k in keys])
        bs2 = np.array([blocks[k][1] for k in keys])
        bc = np.array([blocks[k][2] for k in keys], dtype=float)
        nb = len(keys)
        idx = rng.integers(0, nb, size=(BOOT_N, nb))
        m1 = bs[idx].sum(axis=1) / bc[idx].sum(axis=1)
        m2 = bs2[idx].sum(axis=1) / bc[idx].sum(axis=1)
        out[s] = {
            "n": len(scored),
            "mean_crps_candidate": float(np.mean(
                [r[f"crps_cand_{s}"] for r in scored])),
            "mean_crps_b1_position": float(np.mean(
                [r[f"crps_b1_{s}"] for r in scored])),
            "mean_crps_b2_overall": float(np.mean(
                [r[f"crps_b2_{s}"] for r in scored])),
            "paired_delta_vs_b1": float(np.mean(d1)),
            "ci95_vs_b1": [float(np.percentile(m1, 2.5)),
                           float(np.percentile(m1, 97.5))],
            "paired_delta_vs_b2": float(np.mean(d2)),
            "ci95_vs_b2": [float(np.percentile(m2, 2.5)),
                           float(np.percentile(m2, 97.5))],
            "blocks_iso_weeks": nb,
        }
    return out


def compare(scored, results, calibration, extension, ext_csv_path):
    per_game = {}
    for label, path in (("oct17_csv", None), ("oct18_csv", ext_csv_path)):
        if label == "oct17_csv":
            continue
        # 86 (date, player_id) keys occur twice in BOTH the published
        # CSV and this reproduction (duplicate gamelog events in the
        # snapshot); occurrences pair in order.
        pub = {}
        with open(path) as f:
            for r in csv.DictReader(f):
                pub.setdefault((r["date"], r["player_id"]), []).append(r)
        seen = defaultdict(int)
        worst = 0.0
        matched = 0
        for r in scored:
            key = (r["date"], r["player_id"])
            occ = seen[key]
            seen[key] += 1
            if key not in pub or occ >= len(pub[key]):
                continue
            matched += 1
            prow = pub[key][occ]
            for s in STATS:
                worst = max(worst, abs(
                    r[f"crps_cand_{s}"] - float(prow[f"crps_cand_{s}"])))
        per_game[label] = {"rows_matched": matched,
                           "max_abs_delta_crps_cand": worst}
    stats_cmp = {}
    for s in STATS:
        pub = (calibration["stats"][s] if s in calibration["stats"]
               else extension["stats"][s])
        got = results[s]
        stats_cmp[s] = {
            "published_source": ("nba_props_calibration.json"
                                 if s in calibration["stats"]
                                 else "nba_extension_results.json"),
            "mean_crps_candidate": {
                "published": pub["mean_crps_candidate"],
                "reproduced": got["mean_crps_candidate"],
                "delta": got["mean_crps_candidate"]
                         - pub["mean_crps_candidate"]},
            "mean_crps_b1_position": {
                "published": pub["mean_crps_b1_position"],
                "reproduced": got["mean_crps_b1_position"],
                "delta": got["mean_crps_b1_position"]
                         - pub["mean_crps_b1_position"]},
            "mean_crps_b2_overall": {
                "published": pub["mean_crps_b2_overall"],
                "reproduced": got["mean_crps_b2_overall"],
                "delta": got["mean_crps_b2_overall"]
                         - pub["mean_crps_b2_overall"]},
            "paired_delta_vs_b1": {
                "published": pub["paired_delta_vs_b1"],
                "reproduced": got["paired_delta_vs_b1"],
                "delta": got["paired_delta_vs_b1"]
                         - pub["paired_delta_vs_b1"]},
            "paired_delta_vs_b2": {
                "published": pub["paired_delta_vs_b2"],
                "reproduced": got["paired_delta_vs_b2"],
                "delta": got["paired_delta_vs_b2"]
                         - pub["paired_delta_vs_b2"]},
            "ci95_vs_b1_published": pub["ci95_vs_b1"],
            "ci95_vs_b1_reproduced": got["ci95_vs_b1"],
            "ci95_vs_b2_published": pub["ci95_vs_b2"],
            "ci95_vs_b2_reproduced": got["ci95_vs_b2"],
        }
    return stats_cmp, per_game


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    ap.add_argument("--extension", default=DEFAULT_EXTENSION)
    ap.add_argument("--extension-csv", default=DEFAULT_EXTENSION_CSV)
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "parity_results.json"))
    args = ap.parse_args()

    checks = unit_checks()
    athletes, records, load_counters = load_records(args.snapshot)
    store = GameLogStore(records, season_label="2024-25")
    scored, fallback, dates_sorted = score(store, athletes)
    results = bootstrap(scored)

    with open(os.path.join(args.snapshot, "results",
                           "nba_props_calibration.json")) as f:
        calibration = json.load(f)
    with open(args.extension) as f:
        extension = json.load(f)
    stats_cmp, per_game = compare(
        scored, results, calibration, extension, args.extension_csv)

    counters = {
        "athletes_enumerated": load_counters["athletes_enumerated"],
        "decode_failures": load_counters["decode_failures"],
        "dnp_rows_minutes0": store.counters["excluded_dnp_minutes0"],
        "players_no_position": store.counters["excluded_no_position"],
        "players_in_universe_U": len(store.player_ids()),
        "players_no_regseason_games": (
            load_counters["athletes_enumerated"]
            - store.counters["excluded_no_position"]
            - len(store.player_ids())),
        "players_meeting_min_total_20": int(sum(
            1 for pid in store.player_ids()
            if store.player_total_games(pid) >= MIN_TOTAL)),
        "scored_player_games": len(scored),
        "b1_fallback_to_b2_count": fallback,
        "game_dates": len(dates_sorted),
        "date_range": [dates_sorted[0].isoformat(),
                       dates_sorted[-1].isoformat()],
    }
    published_counters = calibration["counters"]
    counter_deltas = {k: (counters[k], published_counters[k],
                          counters[k] - published_counters[k])
                      for k in published_counters
                      if k in counters
                      and isinstance(published_counters[k], (int, float))}
    max_mean_delta = max(
        abs(stats_cmp[s][field]["delta"])
        for s in STATS
        for field in ("mean_crps_candidate", "mean_crps_b1_position",
                      "mean_crps_b2_overall", "paired_delta_vs_b1",
                      "paired_delta_vs_b2"))
    ok = (len(scored) == published_counters["scored_player_games"]
          and all(v[2] == 0 for v in counter_deltas.values())
          and max_mean_delta <= 1e-9)
    report = {
        "kind": "PARITY_REPRODUCTION",
        "engine_id": "NBA_PROP_EMPIRICAL_V1",
        "snapshot": args.snapshot,
        "unit_checks": checks,
        "counters_reproduced_vs_published": {
            k: {"reproduced": v[0], "published": v[1], "delta": v[2]}
            for k, v in counter_deltas.items()},
        "stats": stats_cmp,
        "per_game_crps_comparison": per_game,
        "max_abs_mean_delta": max_mean_delta,
        "parity_status": "REPRODUCED" if ok else "NOT_REPRODUCED",
    }
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1)
    print(json.dumps({"counters": counters,
                      "max_abs_mean_delta": max_mean_delta,
                      "per_game": per_game,
                      "parity_status": report["parity_status"]}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
