#!/usr/bin/env python3
"""Post-hoc diagnostics for BB-v4's isolated 1.5-walk miss.

This script does not change model math, calibration, thresholds, or deployment state.
It deterministically reconstructs the source-bounded cutoff-correct v4 models and
asks whether the 1.5 miss is primarily a mean shift or a local distribution-shape
error around the 1-walk / 2-walk boundary.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

import scripts.rebuild_pitcher_bb_v4 as base
import scripts.rebuild_pitcher_bb_v4_1 as strict


def fit_probabilities(X, walks, years):
    train = years <= 2024
    calibration = years == 2025
    probabilities = {}
    for line in base.THRESHOLDS:
        y = (walks > line).astype(int)
        model = HistGradientBoostingClassifier(
            learning_rate=.045, max_iter=250, max_leaf_nodes=15,
            min_samples_leaf=100, l2_regularization=3.0, random_state=19,
        )
        model.fit(X[train], y[train])
        raw = model.predict_proba(X)[:, 1]
        calibrator = LogisticRegression(C=100.0, solver="lbfgs").fit(
            base.old.logit(raw[calibration]).reshape(-1, 1), y[calibration]
        )
        probabilities[str(line)] = calibrator.predict_proba(
            base.old.logit(raw).reshape(-1, 1)
        )[:, 1]
    return probabilities


def z_gap(pred, actual, n):
    if n <= 0:
        return None
    denom = np.sqrt(max(actual * (1.0 - actual), 1e-12) / n)
    return float(abs(pred - actual) / denom)


def summary(walks, probs, mask):
    w = walks[mask].astype(int)
    p05 = probs["0.5"][mask]
    p15 = probs["1.5"][mask]
    p25 = probs["2.5"][mask]
    p35 = probs["3.5"][mask]
    n = int(mask.sum())

    actual_mass = {
        "0": float(np.mean(w == 0)),
        "1": float(np.mean(w == 1)),
        "2": float(np.mean(w == 2)),
        "3": float(np.mean(w == 3)),
        "4_plus": float(np.mean(w >= 4)),
    }
    predicted_mass = {
        "0": float(np.mean(1.0 - p05)),
        "1": float(np.mean(p05 - p15)),
        "2": float(np.mean(p15 - p25)),
        "3": float(np.mean(p25 - p35)),
        "4_plus": float(np.mean(p35)),
    }
    mass_gap_pp = {k: 100.0 * (predicted_mass[k] - actual_mass[k]) for k in actual_mass}

    actual_truncated_mean = float(np.mean(np.minimum(w, 4)))
    predicted_truncated_mean = float(np.mean(p05 + p15 + p25 + p35))
    event_actual = float(np.mean(w >= 2))
    event_pred = float(np.mean(p15))

    return {
        "n": n,
        "actual_mean_walks": float(np.mean(w)),
        "actual_truncated_mean_min4": actual_truncated_mean,
        "predicted_truncated_mean_min4": predicted_truncated_mean,
        "truncated_mean_gap": predicted_truncated_mean - actual_truncated_mean,
        "p_ge_2_actual": event_actual,
        "p_ge_2_pred": event_pred,
        "p_ge_2_gap_pp": 100.0 * (event_pred - event_actual),
        "p_ge_2_z": z_gap(event_pred, event_actual, n),
        "actual_walk_count_mass": actual_mass,
        "predicted_walk_count_mass_from_threshold_differences": predicted_mass,
        "walk_count_mass_gap_pp": mass_gap_pp,
        "boundary_1_vs_2_combined_actual": float(np.mean((w == 1) | (w == 2))),
        "boundary_1_vs_2_predicted": float(np.mean((p05 - p15) + (p15 - p25))),
    }


def slices(X, walks, probs, years):
    hold = years == 2026
    out = {"overall_2026": summary(walks, probs, hold)}

    # Feature indexes are frozen by the explicit v4 contract.
    pit_bb = X[:, 0]
    bf_mean = X[:, 3]
    prior_starts = X[:, 4]

    for name, values, cuts in (
        ("prior_pitcher_bb_rate", pit_bb, (0.06, 0.08, 0.10)),
        ("prior_bf_mean", bf_mean, (18.0, 21.0, 24.0)),
        ("prior_starts", prior_starts, (3.0, 8.0, 15.0)),
    ):
        edges = (-np.inf,) + cuts + (np.inf,)
        rows = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            mask = hold & (values >= lo) & (values < hi)
            if int(mask.sum()) < 50:
                continue
            rows.append({"lo": None if np.isneginf(lo) else float(lo),
                         "hi": None if np.isposinf(hi) else float(hi),
                         **summary(walks, probs, mask)})
        out[name] = rows
    return out


def main():
    root = Path(".cache/sportsedge/bb-rebuild")
    games, excluded = strict.fetch_schedule_strict(root / "schedule")
    base.old.ensure_boxes(games, root / "boxscores")
    X, walks, years, identities = base.build_cutoff(games, root / "boxscores")
    probs = fit_probabilities(X, walks, years)
    report = {
        "schema_version": "bb_v4_threshold_15_diagnostics_v1",
        "evidence_class": "POST_HOC_DIAGNOSTIC_NOT_DEPLOYMENT_ATTESTATION",
        "model_math_changed": False,
        "thresholds_changed": False,
        "tolerances_changed": False,
        "chronology_policy": "OFFICIAL_DATE_PRIOR_DAY_SNAPSHOT_APPLY_RESULTS_AFTER_DAY",
        "source_range_policy": "EVERY_RESPONSE_AND_CACHE_ROW_MUST_MATCH_REQUESTED_INTERVAL",
        "source_range_violation_count": sum(1 for x in excluded if x.get("reason_code") == "SOURCE_RANGE_VIOLATION"),
        "rows": int(len(X)),
        "holdout_rows": int((years == 2026).sum()),
        "diagnostics": slices(X, walks, probs, years),
        "interpretation_rule": {
            "mean_shift": "predicted truncated mean materially differs from actual truncated mean",
            "shape_mismatch": "truncated mean is close while mass is materially misallocated between adjacent counts, especially 1 and 2",
        },
    }
    out = Path("artifacts/bb_v4_threshold_15_diagnostics.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["diagnostics"]["overall_2026"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
