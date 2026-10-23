"""NFL anytime-TD engine v1 — calibration leg scorer
(PREREG_NFL_ATD_ENGINE_V1.md §3). RESEARCH_ONLY.

Scores every gated player-game in 2020-2025 point-in-time against two
baselines on identical rows: (a) POOL, the position-group pool rate itself;
(b) RAW, the player's unshrunk unweighted TD rate over the same evidence.
Primary metric log loss; Brier secondary. Paired bootstrap CIs clustered
by game (season, week, unordered team pair), 2,000 resamples, seed 20261018.

Usage: python3 eval_nfl_atd_calibration_v1.py --data DIR --out results.json
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import atd_engine as eng

HERE = Path(__file__).resolve().parent
PREREG_NAME = "PREREG_NFL_ATD_ENGINE_V1.md"
PLAN_SHA256 = "c3907b08041ccd36827aedc7cb3de57c172d41269dde76fbd28a82cd8565e099"
SCORED_SEASONS = tuple(range(2020, 2026))
SEED, RESAMPLES = 20261018, 2000
EPS = 1e-6


def logloss(p: float, y: int) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1.0 - p))


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def build_rows(data: dict):
    """All scored player-games (frozen §3 population) + gate-out counts."""
    rows = []
    gated_out = Counter()
    pool_cache: dict = {}
    for season in SCORED_SEASONS:
        apps = sorted(data["by_season"].get(season, []),
                      key=lambda a: (a["week"], a["pid"]))
        for a in apps:
            pid, week = a["pid"], a["week"]
            ev = eng.evidence_games(data, pid, season, week)
            if len(ev) < eng.MIN_GAMES:
                gated_out["UNPRICED_INSUFFICIENT_GAMES"] += 1
                continue
            group = ev[0]["position_group"]
            if group not in eng.POOL_GROUPS:
                gated_out["UNPRICED_POSITION_GROUP_NOT_POOLED"] += 1
                continue
            priced = eng.price_player(data, pid, season, week,
                                      pool_cache=pool_cache)
            if priced["status"] != "PRICED":
                gated_out[priced["reason"]] += 1
                continue
            teams = tuple(sorted((a["team"], a["opp"])))
            rows.append({
                "season": season, "week": week, "pid": pid,
                "cluster": f"{season}|{week}|{teams[0]}|{teams[1]}",
                "group": group, "y": a["td"], "st_only": 1
                if (a["st_td"] and not a["td"]) else 0,
                "model_p": priced["model_p"],
                "pool_p": priced["pool_rate"],
                "raw_p": priced["raw_rate"],
            })
    rows.sort(key=lambda r: (r["season"], r["week"], r["pid"]))
    return rows, gated_out


def metrics(rows, key):
    ll = float(np.mean([logloss(r[key], r["y"]) for r in rows]))
    br = float(np.mean([brier(r[key], r["y"]) for r in rows]))
    return ll, br


def cluster_bootstrap(rows):
    """Paired per-row loss deltas (engine - baseline), resampled by game
    cluster. Returns {name: (mean_delta, lo, hi)} for log loss and Brier,
    for both baselines."""
    clusters: dict = defaultdict(list)
    for i, r in enumerate(rows):
        clusters[r["cluster"]].append(i)
    keys = sorted(clusters)
    members = [clusters[k] for k in keys]

    def deltas(key, fn):
        return np.array([fn(r["model_p"], r["y"]) - fn(r[key], r["y"])
                         for r in rows])

    series = {
        "POOL": (deltas("pool_p", logloss), deltas("pool_p", brier)),
        "RAW": (deltas("raw_p", logloss), deltas("raw_p", brier)),
    }
    rng = np.random.default_rng(SEED)
    boot = {name: ([], []) for name in series}
    n_clusters = len(keys)
    for _ in range(RESAMPLES):
        pick = rng.integers(0, n_clusters, size=n_clusters)
        idx = np.concatenate([members[j] for j in pick])
        for name, (dll, dbr) in series.items():
            boot[name][0].append(float(dll[idx].mean()))
            boot[name][1].append(float(dbr[idx].mean()))
    out = {}
    for name, (dll, dbr) in series.items():
        ll_boot, br_boot = boot[name]
        out[name] = {
            "delta_logloss": float(dll.mean()),
            "delta_logloss_ci95": [float(np.percentile(ll_boot, 2.5)),
                                   float(np.percentile(ll_boot, 97.5))],
            "delta_brier": float(dbr.mean()),
            "delta_brier_ci95": [float(np.percentile(br_boot, 2.5)),
                                 float(np.percentile(br_boot, 97.5))],
        }
        out[name]["verdict"] = (
            "BEATS_BASELINE" if out[name]["delta_logloss_ci95"][1] < 0
            else "DOES_NOT_BEAT_BASELINE")
    return out


def deciles(rows):
    srt = sorted(rows, key=lambda r: r["model_p"])
    n = len(srt)
    out = []
    for i in range(10):
        chunk = srt[i * n // 10:(i + 1) * n // 10]
        if not chunk:
            continue
        out.append({
            "decile": i + 1, "n": len(chunk),
            "mean_model_p": float(np.mean([r["model_p"] for r in chunk])),
            "realized_rate": float(np.mean([r["y"] for r in chunk])),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data_dir = Path(args.data)
    got_plan = eng.sha256_bytes((HERE / PREREG_NAME).read_bytes())
    if got_plan != PLAN_SHA256:
        raise SystemExit(f"PREREG_HASH_MISMATCH: {got_plan} != {PLAN_SHA256}")
    pins = eng.check_data_pins(data_dir)
    data = eng.load_data(data_dir)
    rows, gated_out = build_rows(data)
    if not rows:
        raise SystemExit("NO_SCORED_ROWS")
    m_ll, m_br = metrics(rows, "model_p")
    results = {
        "label": "NFL ANYTIME TD ENGINE V1 — calibration leg (frozen plan §3)",
        "status_label": "RESEARCH_ONLY", "validation_status": "NOT_VALIDATED",
        "prereg": PREREG_NAME, "prereg_sha256": PLAN_SHA256,
        "data_sha256": pins,
        "construction": {"K_A": eng.K_A, "half_life_games": eng.HALF_LIFE_GAMES,
                         "max_evidence_games": eng.MAX_EVIDENCE_GAMES,
                         "min_games": eng.MIN_GAMES,
                         "pool_min_games": eng.POOL_MIN_GAMES},
        "scored_seasons": list(SCORED_SEASONS),
        "n_scored": len(rows),
        "n_gated_out": dict(gated_out),
        "base_rate": float(np.mean([r["y"] for r in rows])),
        "mean_model_p": float(np.mean([r["model_p"] for r in rows])),
        "st_only_td_rows_in_scored_population":
            int(sum(r["st_only"] for r in rows)),
        "engine": {"logloss": m_ll, "brier": m_br},
        "baselines": {},
        "deciles": deciles(rows),
        "handcheck_rows": [
            {"season": r["season"], "week": r["week"], "pid": r["pid"],
             "model_p": r["model_p"], "pool_p": r["pool_p"],
             "raw_p": r["raw_p"], "y": r["y"]} for r in rows[:12]],
        "bootstrap": {"resamples": RESAMPLES, "seed": SEED,
                      "cluster": "season|week|team_pair"},
    }
    for name, key in (("POOL", "pool_p"), ("RAW", "raw_p")):
        ll, br = metrics(rows, key)
        results["baselines"][name] = {"logloss": ll, "brier": br}
    results["comparisons"] = cluster_bootstrap(rows)
    Path(args.out).write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"n_scored": len(rows), "engine_logloss": m_ll,
                      "comparisons": results["comparisons"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
