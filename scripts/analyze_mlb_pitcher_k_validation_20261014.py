"""Validation analysis for the MLB pitcher-K family (Oct 14, 2026).

Reads the governed Attempt-1 evidence persisted to the data branch
(commit 26a1e4829e2d143a529e05dec2f48ee3ed6100bd:
evidence/mlb_pitcher_k/attempt_1/{rows,summary,evaluation}.json) and:

  1. Reproduces the preregistered readout from the persisted rows using
     the frozen Attempt-1 passed fit (candidate mean RPS and incumbent
     mean RPS on the 2025 test rows) -- an integrity check that the
     persisted rows + frozen fit regenerate the published numbers.
  2. Scores two simple, untuned baselines on the same 2025 rows
     (POST-HOC DESCRIPTIVE comparators; no selection depends on them):
       (a) trailing-rate baseline: the pitcher's own strictly-prior
           recent K/BF feature with the same projected BF and the same
           beta-binomial concentration (100) -- no regression;
       (b) league-constant baseline: the pooled realized K/BF of the
           2023+2024 rows in the evidence file, same BF/concentration.
  3. Reports count log score (mean -log pmf of realized K) for the
     candidate and both baselines.
  4. Reports candidate calibration by predicted-mean band on 2025 rows.

The preregistered 2025 test is one-shot and consumed: nothing here
retunes, reselects, or re-judges the development gate. The market leg
is forward-only (historical DK K lines are not in hand); the frozen
forward protocol requires >= 150 graded prospective units.

Usage: python3 scripts/analyze_mlb_pitcher_k_validation_20261014.py \
           --evidence-dir DIR --out PATH
"""
from __future__ import annotations

import argparse
import json
from math import log
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_mlb_pitcher_k_example_20261014 import load_frozen_fit
from sportsedge.mlb_pitcher_k_probability_candidate import (
    HALF_LINES,
    count_mass,
    feature_vector,
    predict_k_rate,
    rps_for_realized_count,
)

CONCENTRATION = 100.0


def rps_from_p_over(p_over: dict, realized: int) -> float:
    return sum((float(p_over[f"{line:.1f}"]) - (1.0 if realized > line else 0.0)) ** 2
               for line in HALF_LINES) / len(HALF_LINES)


def rps_from_rate(rate: float, n_bf: int, realized: int) -> float:
    mass = count_mass(n_trials=n_bf, k_rate=rate, concentration=CONCENTRATION)
    return sum(((sum(mass[k] for k in range(len(mass)) if k > line))
                 - (1.0 if realized > line else 0.0)) ** 2
               for line in HALF_LINES) / len(HALF_LINES)


def count_log_score(rate: float, n_bf: int, realized: int) -> float:
    mass = count_mass(n_trials=n_bf, k_rate=rate, concentration=CONCENTRATION)
    if realized >= len(mass):
        return float("nan")
    return -log(max(mass[realized], 1e-300))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    ev_dir = Path(args.evidence_dir)
    rows_doc = json.loads((ev_dir / "rows.json").read_text())
    summary = json.loads((ev_dir / "summary.json").read_text())
    rows = rows_doc["rows"] if isinstance(rows_doc, dict) else rows_doc
    fit, concentration, _freeze = load_frozen_fit(Path(__file__).resolve().parents[1])
    assert concentration == CONCENTRATION

    by_season = {}
    for row in rows:
        by_season.setdefault(int(row["season"]), []).append(row)
    train_rows = by_season[2023] + by_season[2024]
    test_rows = by_season[2025]

    league_rate = (sum(r["realized_strikeouts"] for r in train_rows)
                   / sum(r["realized_batters_faced"] for r in train_rows))

    agg = {k: 0.0 for k in (
        "cand_rps", "inc_rps", "trail_rps", "league_rps",
        "cand_ll", "trail_ll", "league_ll")}
    bands: dict[str, dict] = {}
    band_edges = [(0.0, 4.0), (4.0, 5.0), (5.0, 6.0), (6.0, 7.0),
                  (7.0, 8.0), (8.0, float("inf"))]
    for row in test_rows:
        cand = row["candidate"]
        realized = int(row["realized_strikeouts"])
        feats = feature_vector(cand)
        n_bf = int(round(feats[0]))
        cand_rate = predict_k_rate(fit, cand)
        agg["cand_rps"] += rps_for_realized_count(
            cand, fit, concentration=CONCENTRATION,
            realized_strikeouts=realized)
        agg["inc_rps"] += rps_from_p_over(row["incumbent_p_over"], realized)
        agg["trail_rps"] += rps_from_rate(feats[1], n_bf, realized)
        agg["league_rps"] += rps_from_rate(league_rate, n_bf, realized)
        agg["cand_ll"] += count_log_score(cand_rate, n_bf, realized)
        agg["trail_ll"] += count_log_score(feats[1], n_bf, realized)
        agg["league_ll"] += count_log_score(league_rate, n_bf, realized)
        mu = cand_rate * n_bf
        for lo, hi in band_edges:
            if lo <= mu < hi:
                band = bands.setdefault(f"{lo:g}-{hi:g}" if hi != float("inf")
                                        else f"{lo:g}+",
                                        {"n": 0, "mu": 0.0, "realized": 0.0})
                band["n"] += 1
                band["mu"] += mu
                band["realized"] += realized
                break

    n = len(test_rows)
    out = {
        "evidence": {
            "row_count_total": len(rows),
            "train_rows_2023_2024": len(train_rows),
            "test_rows_2025": n,
            "rows_sha256_in_summary": summary["rows_sha256"],
            "readout_candidate_mean_rps": summary["metrics"]["candidate_mean_rps"],
            "readout_incumbent_mean_rps": summary["metrics"]["incumbent_mean_rps"],
        },
        "reproduction": {
            "candidate_mean_rps": agg["cand_rps"] / n,
            "incumbent_mean_rps": agg["inc_rps"] / n,
        },
        "baselines_posthoc_descriptive": {
            "league_constant_rate": league_rate,
            "trailing_rate_mean_rps": agg["trail_rps"] / n,
            "league_constant_mean_rps": agg["league_rps"] / n,
        },
        "count_log_score_mean": {
            "candidate": agg["cand_ll"] / n,
            "trailing_rate": agg["trail_ll"] / n,
            "league_constant": agg["league_ll"] / n,
        },
        "calibration_by_predicted_mean_band": {
            k: {"n": v["n"], "mean_predicted": v["mu"] / v["n"],
                "mean_realized": v["realized"] / v["n"]}
            for k, v in sorted(bands.items())
        },
    }
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
