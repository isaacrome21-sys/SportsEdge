"""Recompute every number in results.json from metrics_input.jsonl alone
and assert agreement (fresh-worktree reproduction check for step 7).

Usage: verify_results.py <metrics_input.jsonl> <manifest.json> <results.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics as mx  # noqa: E402

TOL = 1e-9


def close(a, b):
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


def main() -> None:
    inp, manifest_path, results_path = (Path(sys.argv[1]), Path(sys.argv[2]),
                                        Path(sys.argv[3]))
    manifest = json.loads(manifest_path.read_text())
    typical = manifest["folds"]["2025"]["typical_lines"]
    results = json.loads(results_path.read_text())
    recs = [json.loads(x) for x in inp.read_text().splitlines() if x.strip()]
    n = len(recs)
    assert n == results["games_scored_fold_2025"], (n, results["games_scored_fold_2025"])
    failures = []
    rng = np.random.default_rng(mx.BOOT_SEED)
    for market, agg in (("GAME_TOTAL_HITS", "game"), ("TEAM_TOTAL_HITS", "team")):
        cell = results["markets"][market]
        if agg == "game":
            vals = {s: np.array([r["rps"][s]["game"] for r in recs]) for s in mx.SCORERS}
            over = {s: [(r["pover"][s]["game"],
                         1.0 if r["realized"]["game"] > typical[market] else 0.0)
                        for r in recs] for s in mx.SCORERS}
        else:
            vals = {s: np.array([0.5 * (r["rps"][s]["away"] + r["rps"][s]["home"])
                                 for r in recs]) for s in mx.SCORERS}
            over = {s: [(r["pover"][s][side],
                         1.0 if r["realized"][side] > typical[market] else 0.0)
                        for r in recs for side in ("away", "home")] for s in mx.SCORERS}
        mean_rps = {s: float(np.mean(vals[s])) for s in mx.SCORERS}
        for s in mx.SCORERS:
            if not close(mean_rps[s], cell["mean_rps"][s]):
                failures.append(f"{market} mean_rps[{s}] {mean_rps[s]} != {cell['mean_rps'][s]}")
        best = min((s for s in mx.SCORERS if s != "candidate"), key=lambda s: mean_rps[s])
        if best != cell["best_baseline"]:
            failures.append(f"{market} best {best} != {cell['best_baseline']}")
        delta = vals["candidate"] - vals[best]
        reps = np.empty(mx.BOOT_REPS)
        for i in range(mx.BOOT_REPS):
            idx = rng.integers(0, n, n)
            reps[i] = float(np.mean(delta[idx]))
        ci = [float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))]
        if not close(float(np.mean(delta)), cell["delta_vs_best"]):
            failures.append(f"{market} delta mismatch")
        if not (close(ci[0], cell["bootstrap_ci95"][0]) and close(ci[1], cell["bootstrap_ci95"][1])):
            failures.append(f"{market} CI mismatch {ci} vs {cell['bootstrap_ci95']}")
        ece_c, ll_c = mx.ece_logloss(over["candidate"], typical[market])
        ece_b, ll_b = mx.ece_logloss(over[best], typical[market])
        if not (close(ece_c, cell["ece"]["candidate"]) and close(ece_b, cell["ece"]["best_baseline"])):
            failures.append(f"{market} ECE mismatch")
        if not (close(ll_c, cell["logloss"]["candidate"]) and close(ll_b, cell["logloss"]["best_baseline"])):
            failures.append(f"{market} logloss mismatch")
        legs = {"rps_ci_high_below_0": bool(ci[1] < 0),
                "ece_within_best_plus_0.005": bool(ece_c <= ece_b + 0.005),
                "logloss_not_worse_than_best": bool(ll_c <= ll_b)}
        if legs != cell["fold_2025_legs"]:
            failures.append(f"{market} legs mismatch {legs} vs {cell['fold_2025_legs']}")
        print(market, "recomputed: best =", best, "| delta =", round(float(np.mean(delta)), 6),
              "| CI =", [round(x, 6) for x in ci], "| legs =", legs)
    if failures:
        print("VERIFY FAILED:")
        [print(" -", f) for f in failures]
        sys.exit(1)
    print(f"VERIFY OK: all tables in results.json reproduce from metrics_input.jsonl ({n} games)")


if __name__ == "__main__":
    main()
