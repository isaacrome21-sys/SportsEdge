#!/usr/bin/env python3
"""Budget-neutral paired uncertainty diagnostic for frozen NFL attempt one.

Reproduces the already-evaluated 2010-2018 -> 2019 baseline and opponent-strength
candidate, then estimates uncertainty in RMSE differences by paired bootstrap.
No new feature/model candidate is introduced and no search-budget attempt is consumed.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fit_football_baselines", ROOT / "scripts" / "fit_football_baselines.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

SEASONS = set(range(2010, 2020))
HOLDOUT = 2019
BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20260910


def fit_predict(xtr, ytr, xte, alpha):
    a, b = mod.scale(xtr, xte)
    beta, intercept = mod.fit(a, ytr, alpha)
    return b @ beta + intercept


def select_alpha(xtr, ytr):
    ms = {a: [] for a in mod.ALPHAS}
    n = len(ytr)
    for k in range(1, 5):
        cut = max(20, int(n * k / 5))
        end = max(cut + 1, int(n * (k + 1) / 5))
        a, b = mod.scale(xtr[:cut], xtr[cut:end])
        for alpha in mod.ALPHAS:
            beta, intercept = mod.fit(a, ytr[:cut], alpha)
            pred = b @ beta + intercept
            ms[alpha].append(float(np.mean((pred - ytr[cut:end]) ** 2)))
    return min(ms, key=lambda z: np.mean(ms[z]))


def usable_market_rows(games):
    from collections import defaultdict
    from itertools import groupby
    games = sorted(games, key=lambda z: (z["date"], z["id"]))
    prior = defaultdict(int)
    keyed = []
    for d, grp in groupby(games, key=lambda z: z["date"]):
        batch = list(grp)
        for g in batch:
            if prior[g["home"]] >= 5 and prior[g["away"]] >= 5:
                keyed.append(g)
        for g in batch:
            prior[g["home"]] += 1
            prior[g["away"]] += 1
    return keyed


def rmse(pred, actual):
    return float(np.sqrt(np.mean((pred - actual) ** 2)))


def paired_bootstrap(a_pred, b_pred, actual, reps=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED):
    rng = np.random.default_rng(seed)
    n = len(actual)
    deltas = np.empty(reps, dtype=float)
    for i in range(reps):
        idx = rng.integers(0, n, n)
        deltas[i] = rmse(a_pred[idx], actual[idx]) - rmse(b_pred[idx], actual[idx])
    return {
        "reps": reps,
        "seed": seed,
        "n": n,
        "observed_delta_rmse": rmse(a_pred, actual) - rmse(b_pred, actual),
        "bootstrap_se": float(np.std(deltas, ddof=1)),
        "ci95_percentile": [float(np.quantile(deltas, 0.025)), float(np.quantile(deltas, 0.975))],
        "q05": float(np.quantile(deltas, 0.05)),
        "q50": float(np.quantile(deltas, 0.50)),
        "q95": float(np.quantile(deltas, 0.95)),
        "prob_delta_lt_zero": float(np.mean(deltas < 0.0)),
    }


def model_for_feature_set(games, feature_set):
    X, ym, _, _, dates = mod.features(games, feature_set)
    hold = np.asarray([d.startswith(str(HOLDOUT)) for d in dates])
    xtr, ytr, xte, yte = X[~hold], ym[~hold], X[hold], ym[hold]
    alpha = select_alpha(xtr, ytr)
    pred = fit_predict(xtr, ytr, xte, alpha)
    return {"alpha": float(alpha), "actual": yte, "pred": pred, "n": int(len(yte))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts/nfl_attempt1_uncertainty.json")
    args = ap.parse_args()

    games, source_sha, source = mod.nfl(SEASONS)
    games = [g for g in games if int(g["date"][:4]) <= HOLDOUT]
    baseline = model_for_feature_set(games, "baseline")
    candidate = model_for_feature_set(games, "opponent_strength")
    if baseline["n"] != candidate["n"] or not np.array_equal(baseline["actual"], candidate["actual"]):
        raise RuntimeError("HOLDOUT_ALIGNMENT_MISMATCH")

    market_rows = usable_market_rows(games)
    market_hold = [g for g in market_rows if g["date"].startswith(str(HOLDOUT))]
    if len(market_hold) != baseline["n"]:
        raise RuntimeError(f"MARKET_ALIGNMENT_MISMATCH:{len(market_hold)}:{baseline['n']}")
    close = np.asarray([g["spread_line"] for g in market_hold], dtype=float)
    actual = baseline["actual"]
    corr = float(np.corrcoef(close, actual)[0, 1])
    if not np.isfinite(corr) or corr <= 0:
        raise RuntimeError(f"SPREAD_ORIENTATION_REJECTED:{corr}")

    report = {
        "schema": "NFL_ATTEMPT1_PAIRED_UNCERTAINTY_V1",
        "status": "RESEARCH_ONLY_BUDGET_NEUTRAL_DIAGNOSTIC",
        "training_seasons": list(range(2010, 2019)),
        "holdout_season": HOLDOUT,
        "source": source,
        "source_sha256": source_sha,
        "n_holdout": int(len(actual)),
        "spread_line_home_margin_correlation": corr,
        "rmse": {
            "baseline": rmse(baseline["pred"], actual),
            "opponent_strength_attempt1": rmse(candidate["pred"], actual),
            "closing_spread": rmse(close, actual),
        },
        "selected_alpha": {
            "baseline": baseline["alpha"],
            "opponent_strength_attempt1": candidate["alpha"],
        },
        "paired_bootstrap": {
            "baseline_minus_close": paired_bootstrap(baseline["pred"], close, actual),
            "attempt1_minus_baseline": paired_bootstrap(candidate["pred"], baseline["pred"], actual),
            "attempt1_minus_close": paired_bootstrap(candidate["pred"], close, actual),
        },
        "budget_accounting": {
            "attempts_before": 1,
            "attempts_after": 1,
            "reason": "Reproduces existing baseline and already-read attempt-one candidate only; no feature/model revision.",
            "post_result_policy_note": "The control-calibration budget exemption was formalized after attempt one had already read out. It is retained solely as bookkeeping for the required denominator and must not be treated as clean preregistration precedent for future exemptions."
        }
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
