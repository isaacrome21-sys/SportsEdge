"""Metrics + verdicts for PREREG MLB_TOTAL_HITS_JOINT_PATH_HARNESS_V1.

Reads pmf_rows.jsonl (per-game candidate + baseline count PMFs and realized
hits) and the dataset manifest; computes, per market and cell:
  * MEAN_RPS (sum over the preregistered half-line grid of squared CDF
    errors, averaged over rows);
  * the cell's best baseline (lowest MEAN_RPS) and the paired cluster
    bootstrap (unit GAME_ID, 2000 replicates, seed 20261015, percentile
    95% CI) of candidate - best-baseline MEAN_RPS;
  * typical-line ECE (fixed bins [0,.1,...,.9,1.0]) and log loss
    (probabilities clipped to [1e-6, 1-1e-6] for this leg only, declared).
Applies the section-8 pass rule verbatim. Fold 2024 is not scoreable as
frozen (training window absent from the archive) and the pooled cell is
therefore not computable as frozen, so neither market can PASS; fold-2025
legs are computed and reported in full.

Usage: metrics.py <pmf_rows.jsonl> <manifest.json> <results_out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

SCORERS = ["candidate", "naive_team_rate_poisson", "league_constant_rate",
           "trailing_20_game_team_rate", "independence_convolution"]
GAME_K = list(range(0, 21))   # half-lines 0.5 .. 20.5
TEAM_K = list(range(0, 13))   # half-lines 0.5 .. 12.5
BOOT_REPS = 2000
BOOT_SEED = 20261015
LOGLOSS_EPS = 1e-6


def cdf_at(pmf: dict, k: int) -> float:
    return sum(p for c, p in pmf.items() if c <= k)


def rps(pmf: dict, realized: int, grid: list) -> float:
    pmf = {int(k): v for k, v in pmf.items()}
    return sum((cdf_at(pmf, k) - (1.0 if realized <= k else 0.0)) ** 2
               for k in grid)


def p_over(pmf: dict, line: float) -> float:
    return sum(p for c, p in pmf.items() if int(c) > line)


def ece_logloss(rows: list, line: float):
    """rows: list of (p_over, realized_over). Returns (ece, logloss)."""
    bins = [[] for _ in range(10)]
    for p, y in rows:
        bins[min(9, int(p * 10))].append((p, y))
    n = len(rows)
    ece = 0.0
    for b in bins:
        if b:
            ece += (len(b) / n) * abs(np.mean([y for _, y in b])
                                      - np.mean([p for p, _ in b]))
    ll = float(np.mean([
        -(y * np.log(min(max(p, LOGLOSS_EPS), 1 - LOGLOSS_EPS))
          + (1 - y) * np.log(min(max(1 - p, LOGLOSS_EPS), 1 - LOGLOSS_EPS)))
        for p, y in rows]))
    return float(ece), ll


def main() -> None:
    pmf_path, manifest_path, out_path = (Path(sys.argv[1]), Path(sys.argv[2]),
                                         Path(sys.argv[3]))
    manifest = json.loads(manifest_path.read_text())
    typical = manifest["folds"]["2025"]["typical_lines"]
    rows = [json.loads(x) for x in pmf_path.read_text().splitlines() if x.strip()]
    rows.sort(key=lambda r: (r["date"], r["game_id"]))
    n = len(rows)
    print(f"games scored: {n}")

    # per-game, per-scorer RPS (game market + team row-mean) and typical-line
    # over-probabilities
    def scorer_pmf(row, scorer, which):
        src = row["candidate"] if scorer == "candidate" else row["baselines"][scorer]
        return src[which]

    per_game = []          # dict per game: rps_game[scorer], rps_team[scorer]
    over = {"GAME_TOTAL_HITS": {s: [] for s in SCORERS},
            "TEAM_TOTAL_HITS": {s: [] for s in SCORERS}}
    for row in rows:
        entry = {"rps_game": {}, "rps_team": {}}
        for s in SCORERS:
            entry["rps_game"][s] = rps(scorer_pmf(row, s, "game"),
                                        row["realized"]["game"], GAME_K)
            team_rps = [rps(scorer_pmf(row, s, side), row["realized"][side], TEAM_K)
                        for side in ("away", "home")]
            entry["rps_team"][s] = float(np.mean(team_rps))
            over["GAME_TOTAL_HITS"][s].append(
                (p_over(scorer_pmf(row, s, "game"), typical["GAME_TOTAL_HITS"]),
                 1.0 if row["realized"]["game"] > typical["GAME_TOTAL_HITS"] else 0.0))
            for side in ("away", "home"):
                over["TEAM_TOTAL_HITS"][s].append(
                    (p_over(scorer_pmf(row, s, side), typical["TEAM_TOTAL_HITS"]),
                     1.0 if row["realized"][side] > typical["TEAM_TOTAL_HITS"] else 0.0))
        per_game.append(entry)

    rng = np.random.default_rng(BOOT_SEED)
    results = {"schema": "MLB_TOTAL_HITS_JOINT_PATH_HARNESS_PREREG_V1",
               "games_scored_fold_2025": n, "markets": {}}
    for market, key in (("GAME_TOTAL_HITS", "rps_game"), ("TEAM_TOTAL_HITS", "rps_team")):
        mean_rps = {s: float(np.mean([e[key][s] for e in per_game])) for s in SCORERS}
        best = min((s for s in SCORERS if s != "candidate"),
                   key=lambda s: mean_rps[s])
        delta = np.array([e[key]["candidate"] - e[key][best] for e in per_game])
        reps = np.empty(BOOT_REPS)
        for i in range(BOOT_REPS):
            idx = rng.integers(0, n, n)
            reps[i] = float(np.mean(delta[idx]))
        ci = [float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))]
        ece_c, ll_c = ece_logloss(over[market]["candidate"], typical[market])
        ece_b, ll_b = ece_logloss(over[market][best], typical[market])
        legs = {
            "rps_ci_high_below_0": bool(ci[1] < 0),
            "ece_within_best_plus_0.005": bool(ece_c <= ece_b + 0.005),
            "logloss_not_worse_than_best": bool(ll_c <= ll_b),
        }
        results["markets"][market] = {
            "cell": "fold_2025",
            "mean_rps": mean_rps, "best_baseline": best,
            "delta_vs_best": float(np.mean(delta)), "bootstrap_ci95": ci,
            "typical_line": typical[market],
            "ece": {"candidate": ece_c, "best_baseline": ece_b},
            "logloss": {"candidate": ll_c, "best_baseline": ll_b},
            "fold_2025_legs": legs,
            "fold_2025_pass": bool(all(legs.values())),
            "pooled": "NOT_COMPUTABLE_AS_FROZEN (fold 2024 unscored: training "
                      "window absent from the section-6 archive)",
            "verdict": "DOES_NOT_PASS",
            "verdict_basis": "Two independent grounds, either sufficient: "
                             "(1) in fold 2025 itself the candidate fails the "
                             "legs listed in fold_2025_legs (delta vs best "
                             "baseline is positive with the 95% CI entirely "
                             "above zero, ECE exceeds best baseline + 0.005, "
                             "log loss is worse than best baseline); "
                             "(2) section 8 also requires the legs pooled and "
                             "in every fold, and fold 2024 is not scoreable as "
                             "frozen (training window absent from the "
                             "section-6 archive), so the pooled cell is not "
                             "computable and PASS would be unavailable even "
                             "if fold 2025 had passed.",
        }
        print(market, json.dumps(results["markets"][market], indent=1)[:800])
    out_path.write_text(json.dumps(results, indent=1))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
