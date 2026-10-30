"""Development evaluation + records for NFL_SCORE_COUNTS_G2 attempt 2.

Gate standards are attempt-1's, verbatim (preregistration section 5;
threshold provenance cross-checked against
``config/research/nfl_score_counts_g2_prereg_v1.json`` - see the
preregistration package's section 9 table). Attempt-2 changes are confined
to the candidate's construction and the G-JOINT comparator set:

* comparator (ii') - the independent-marginals composition of the
  candidate's own PMF - replaces the attempt-1 discrete_v2 leg as the
  second runnable development comparator (ruling J1). Per Amendment 1 it
  is governed as a DEPENDENCE-VALUE test derived from the candidate's own
  PMF, NOT an independent external benchmark, and no record produced here
  may present it as one.
* the discrete_v2 leg is recorded with status UNEVALUATED: it cannot pass
  or fail the development gate, is not waived, and no development PASS may
  be represented as satisfying it. It is not implemented here.
* G-JOINT, G-CAL and G-KEY consume the candidate (post-K3) PMF;
  skeleton-PMF key errors are computed and reported as diagnostics.

A required comparison that cannot be run makes its gate FAIL with the
reason recorded (the attempt-1 G_JOINT_BASELINE_II_NOT_RUNNABLE pattern);
no gate is ever left INDETERMINATE in a result record. Pre-scoring aborts
(source failure, fold below the 250-game minimum, paths below the scored
minimum) produce NOT_RUN records and do not consume the attempt.

EXECUTION STATUS: attempt 2 is NOT authorized (owner NO-GO, Oct 13 2026).
This module is exercised only by synthetic tests; the governed runner
refuses by construction.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import log
from typing import Any, Mapping, Sequence

import numpy as np

from sportsedge.sports.nfl.score_counts_g1 import predict_mean as heritage_predict_mean

from sportsedge.research.nfl_score_counts_g2_v2 import (
    ATTEMPT_NUMBER,
    K3_KEYS,
    MIN_PATHS_FOR_SCORED_OUTPUT,
    PATHS_PER_GAME,
    ROOT_SEED_LITERAL_V2,
    ROOT_SEED_SHA256_V2,
    VALIDATION_SEASONS,
    V2_CONFIG,
    ModelFormConfig,
    ScoreCountsG2V2Error,
    apply_k3,
    banded_made_fg_detail,
    banded_made_fg_mean,
    estimate_k3_lambdas,
    fit_fold_bundle,
    fold_rare_rates,
    game_pairs,
    independent_marginals_pmf,
    log_score,
    log_score_pmf,
    margin_law,
    pmf_counts,
    pmf_from_counts,
    poisson_deviance,
    poisson_logpmf,
    randomized_pit,
    realized_final_score,
    rng_for_v2,
    row_has_band_context,
    select_sigma_nested_v2,
    simulate_full_game_v2,
    simulate_period_game_v2,
)

# Gate constants - attempt-1 standards verbatim (preregistration section 9
# provenance: config/research/nfl_score_counts_g2_prereg_v1.json).
RARE_TOLERANCE = 1e-12
CAL_SLOPE_BOUNDS = (0.9, 1.1)
CAL_MARGIN_DEV_BOUND = 0.05
KEY_ABS_BOUND = 0.0075
MIN_FOLD_WINS = 3
FOLD_MIN_GAMES = 250

ATTEMPT_BUDGET = 3
ATTEMPTS_CONSUMED_BEFORE = 1  # attempt 1, DEVELOPMENT_ATTEMPT_FAIL, Oct 12 2026

AUTHORITY = {
    "research_only": True,
    "creates_model_p": False,
    "phone_card": False,
    "truth_gate": False,
    "promotion": False,
    "staking": False,
    "official": False,
}

DISCRETE_V2_LEG = {
    "status": "UNEVALUATED",
    "reason": (
        "The discrete_v2 comparison is a prospective-stage requirement under "
        "ruling J1. It cannot pass or fail the development gate, is not "
        "waived, and no development PASS may be represented as satisfying it."
    ),
}


class NotRunError(ScoreCountsG2V2Error):
    """Pre-scoring abort: the attempt is NOT_RUN and NOT consumed."""


def fail_gate(reason: str, **detail: Any) -> dict[str, Any]:
    """The INDETERMINATE-to-FAIL rule: a required comparison that cannot be
    run is a gate FAIL with the reason recorded, never an open state."""
    out = {"pass": False, "status": "FAIL", "reason": reason}
    out.update(detail)
    return out


def _decile_slope(pits: np.ndarray) -> float:
    midpoints = np.asarray([0.05 + 0.1 * k for k in range(10)], dtype=float)
    observed = np.asarray([float(np.mean(pits <= m)) for m in midpoints], dtype=float)
    x = midpoints
    return float(np.cov(x, observed, ddof=0)[0, 1] / np.var(x))


def _decile_max_deviation(pits: np.ndarray) -> float:
    bins = np.histogram(pits, bins=10, range=(0.0, 1.0))[0] / max(len(pits), 1)
    return float(np.max(np.abs(bins - 0.1)))


def randomized_pit_from_law(law: Mapping[int, float], realized: int,
                            rng: np.random.Generator) -> float:
    below = sum(p for v, p in law.items() if v < realized)
    equal = float(law.get(realized, 0.0))
    return float(below + float(rng.random()) * equal)


# ---------------------------------------------------------------------------
# Pure gate-verdict helpers (synthetic-record testable).
# ---------------------------------------------------------------------------

def assemble_count_gate(fold_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold rule for the deviance gates (G-TD / G-FG): candidate better
    pooled AND in at least MIN_FOLD_WINS of the folds."""
    y = np.concatenate([np.asarray(f["y"], dtype=float) for f in fold_rows])
    cand = np.concatenate([np.asarray(f["cand"], dtype=float) for f in fold_rows])
    base = np.concatenate([np.asarray(f["base"], dtype=float) for f in fold_rows])
    cand_dev = poisson_deviance(y, cand)
    base_dev = poisson_deviance(y, base)
    wins = sum(1 for f in fold_rows if f["fold_win"])
    folds = [{
        "validation_season": f["validation_season"],
        "n_team_rows": f["n_team_rows"],
        "candidate_poisson_deviance": f["candidate_poisson_deviance"],
        "intercept_baseline_poisson_deviance": f["intercept_baseline_poisson_deviance"],
        "fold_win": bool(f["fold_win"]),
    } for f in fold_rows]
    return {
        "pooled_candidate_poisson_deviance": cand_dev,
        "pooled_intercept_baseline_poisson_deviance": base_dev,
        "pooled_improvement": base_dev - cand_dev,
        "fold_wins": wins,
        "folds_total": len(fold_rows),
        "minimum_fold_wins": MIN_FOLD_WINS,
        "pass": bool(cand_dev < base_dev and wins >= MIN_FOLD_WINS),
        "folds": folds,
    }


def assemble_rare_gate(candidate_ll: float, baseline_ll: float, n: int) -> dict[str, Any]:
    return {
        "metric": "pooled Poisson log score, def_st_touchdowns + safeties",
        "candidate_pooled_log_score": float(candidate_ll),
        "league_rate_baseline_pooled_log_score": float(baseline_ll),
        "n_team_rows": int(n),
        "no_harm_tolerance": RARE_TOLERANCE,
        "pass": bool(candidate_ll >= baseline_ll - RARE_TOLERANCE),
    }


def assemble_joint_gate(
    fold_rows: Sequence[Mapping[str, Any]],
    *,
    leg_ii_prime_available: bool = True,
    leg_ii_prime_unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """G-JOINT: the candidate must beat BOTH runnable legs, pooled and in
    >= MIN_FOLD_WINS folds per leg. The discrete_v2 leg is recorded
    UNEVALUATED and plays no part in the verdict."""
    total_games = sum(f["n_games"] for f in fold_rows)
    cand_pooled = sum(f["candidate_mean_log_score"] * f["n_games"] for f in fold_rows) / total_games
    base_i_pooled = sum(f["baseline_i_mean_log_score"] * f["n_games"] for f in fold_rows) / total_games
    wins_i = sum(1 for f in fold_rows if f["fold_win_vs_baseline_i"])
    leg_i = {
        "pooled_candidate_mean_log_score": cand_pooled,
        "pooled_baseline_mean_log_score": base_i_pooled,
        "fold_wins": wins_i,
        "folds_total": len(fold_rows),
        "pass_vs_baseline_i": bool(cand_pooled > base_i_pooled and wins_i >= MIN_FOLD_WINS),
        "folds": list(fold_rows),
    }
    if not leg_ii_prime_available:
        return {
            "baseline_i_league_empirical_pmf": leg_i,
            "baseline_ii_prime_independent_marginals": fail_gate(
                leg_ii_prime_unavailable_reason or "COMPARATOR_II_PRIME_NOT_RUNNABLE"),
            "baseline_ii_frozen_discrete_v2_grid": dict(DISCRETE_V2_LEG),
            "pass": False,
            "verdict_reason": (
                "A required comparison (ii') could not be run; per the frozen "
                "rule the gate FAILS with the reason recorded."),
        }
    prime_pooled = sum(f["baseline_ii_prime_mean_log_score"] * f["n_games"] for f in fold_rows) / total_games
    wins_prime = sum(1 for f in fold_rows if f["fold_win_vs_baseline_ii_prime"])
    leg_prime = {
        "construction": (
            "Independent-marginals composition of the candidate's own "
            "post-component PMF: P(h, a) = P^H(h) * P^A(a), same PMF floor."),
        "governance": (
            "Dependence-value test derived from the candidate's own PMF "
            "(Amendment 1). NOT an independent external benchmark; this leg "
            "must not be represented as one."),
        "pooled_candidate_mean_log_score": cand_pooled,
        "pooled_baseline_mean_log_score": prime_pooled,
        "fold_wins": wins_prime,
        "folds_total": len(fold_rows),
        "pass_vs_baseline_ii_prime": bool(
            cand_pooled > prime_pooled and wins_prime >= MIN_FOLD_WINS),
    }
    passed = bool(leg_i["pass_vs_baseline_i"] and leg_prime["pass_vs_baseline_ii_prime"])
    return {
        "baseline_i_league_empirical_pmf": leg_i,
        "baseline_ii_prime_independent_marginals": leg_prime,
        "baseline_ii_frozen_discrete_v2_grid": dict(DISCRETE_V2_LEG),
        "pass": passed,
    }


def assemble_cal_gate(total_pits: Sequence[float], margin_pits: Sequence[float]) -> dict[str, Any]:
    total_arr = np.asarray(total_pits, dtype=float)
    margin_arr = np.asarray(margin_pits, dtype=float)
    slope = _decile_slope(total_arr)
    margin_dev = _decile_max_deviation(margin_arr)
    return {
        "total_pit_decile_slope": slope,
        "total_pit_slope_bounds": list(CAL_SLOPE_BOUNDS),
        "margin_pit_max_decile_deviation": margin_dev,
        "margin_pit_deviation_bound": CAL_MARGIN_DEV_BOUND,
        "n_games": int(len(total_arr)),
        "pass": bool(CAL_SLOPE_BOUNDS[0] <= slope <= CAL_SLOPE_BOUNDS[1]
                     and margin_dev <= CAL_MARGIN_DEV_BOUND),
    }


def assemble_key_gate(
    candidate_mass: Mapping[int, Sequence[float]],
    skeleton_mass: Mapping[int, Sequence[float]],
    realized_margins: Sequence[int],
) -> dict[str, Any]:
    realized_arr = np.asarray(realized_margins)
    detail: dict[str, Any] = {}
    skeleton_detail: dict[str, Any] = {}
    key_pass = True
    for k in K3_KEYS:
        model_p = float(np.mean(candidate_mass[k]))
        realized_freq = float(np.mean(realized_arr == k))
        err = abs(model_p - realized_freq)
        detail[str(k)] = {
            "model_probability": model_p, "realized_frequency": realized_freq,
            "abs_error": err, "pass": bool(err <= KEY_ABS_BOUND),
        }
        key_pass = key_pass and err <= KEY_ABS_BOUND
        skel_p = float(np.mean(skeleton_mass[k]))
        skeleton_detail[str(k)] = {
            "model_probability": skel_p, "realized_frequency": realized_freq,
            "abs_error": abs(skel_p - realized_freq),
        }
    return {
        "keys": detail,
        "bound_each": KEY_ABS_BOUND,
        "pass": bool(key_pass),
        "skeleton_diagnostic": {
            "keys": skeleton_detail,
            "note": ("Skeleton (pre-component) key errors are diagnostics "
                     "only; the gate consumes the candidate PMF."),
        },
    }


def assemble_period_gate(
    family_scores: Mapping[str, Mapping[int, Mapping[str, float]]],
    family_baselines: Mapping[str, Mapping[int, Mapping[str, float]]],
    *,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fam in family_scores:
        folds = []
        wins = 0
        cand_sum = 0.0
        base_sum = 0.0
        n_sum = 0
        for season in validation_seasons:
            c = family_scores[fam][season]
            b = family_baselines[fam][season]
            win = c["candidate_mean_log_score"] > b["baseline_mean_log_score"]
            wins += int(win)
            cand_sum += c["candidate_mean_log_score"] * c["n"]
            base_sum += b["baseline_mean_log_score"] * b["n"]
            n_sum += c["n"]
            folds.append({
                "validation_season": season,
                "n_period_observations": c["n"],
                "candidate_mean_log_score": c["candidate_mean_log_score"],
                "baseline_mean_log_score": b["baseline_mean_log_score"],
                "fold_win": bool(win),
            })
        cand_pooled = cand_sum / n_sum if n_sum else 0.0
        base_pooled = base_sum / n_sum if n_sum else 0.0
        out[fam] = {
            "pooled_candidate_mean_log_score": cand_pooled,
            "pooled_baseline_mean_log_score": base_pooled,
            "fold_wins": wins,
            "folds_total": len(validation_seasons),
            "minimum_fold_wins": MIN_FOLD_WINS,
            "pass": bool(cand_pooled > base_pooled and wins >= MIN_FOLD_WINS),
            "folds": folds,
        }
    return out


# ---------------------------------------------------------------------------
# Evaluation driver. Mirrors attempt-1's two-pass structure with the
# preregistered attempt-2 ordering: fold fits with per-fold nested sigma
# selection inside each training window (Amendment 2; section 6 governs)
# -> per-fold K3 estimation from TRAINING games only -> evaluation
# simulation. Estimation strictly precedes evaluation simulation within
# every fold.
# ---------------------------------------------------------------------------

def _rate_lookup(rows: Sequence[Mapping[str, Any]],
                 rates: Sequence[tuple[float, float]]) -> dict[tuple[str, str], tuple[float, float]]:
    return {(str(r["game_id"]), str(r["team"])): rates[i] for i, r in enumerate(rows)}


def run_development_evaluation_v2(
    rows: Sequence[Mapping[str, Any]],
    *,
    paths: int = PATHS_PER_GAME,
    config: ModelFormConfig = V2_CONFIG,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
    fold_min_games: int = FOLD_MIN_GAMES,
) -> dict[str, Any]:
    rows = list(rows)
    if paths < MIN_PATHS_FOR_SCORED_OUTPUT:
        raise NotRunError(
            f"PATHS_BELOW_SCORED_MINIMUM:{paths}<{MIN_PATHS_FOR_SCORED_OUTPUT} "
            "— attempt NOT_RUN (pre-scoring)")
    folds_split: dict[int, tuple[list, list]] = {}
    for season in validation_seasons:
        train = [r for r in rows if int(r["season"]) < season]
        valid = [r for r in rows if int(r["season"]) == season]
        n_games = len(game_pairs(valid)) if valid else 0
        if n_games < fold_min_games:
            raise NotRunError(
                f"FOLD_BELOW_MINIMUM:{season}:{n_games}<{fold_min_games} "
                "— attempt NOT_RUN (data failure)")
        folds_split[season] = (train, valid)

    fold_bundles: dict[int, dict[str, Any]] = {}
    fold_meta: dict[int, dict[str, Any]] = {}
    fold_rate_maps: dict[int, dict[str, Any]] = {}
    sigma_by_fold: dict[int, float] = {}
    sigma_selection: dict[int, dict[str, Any]] = {}
    td_folds: list[dict[str, Any]] = []
    fg_folds: list[dict[str, Any]] = []
    rare_candidate_ll = 0.0
    rare_baseline_ll = 0.0
    rare_n = 0
    fg_exclusions = {"attempts_missing_distance": 0, "makes_missing_distance": 0}
    zero_model_counts = {"fg_gate_rows": 0, "k3_training_games": 0,
                         "validation_games": 0}
    fg_exclusions_by_fold: list[dict[str, Any]] = []
    band_pooled = {
        "realized_attempts": [0] * 5, "realized_makes": [0] * 5,
        "expected_attempts": [0.0] * 5, "expected_makes": [0.0] * 5,
        "expected_opportunity_total": 0.0, "n_team_rows": 0,
    }
    band_folds: list[dict[str, Any]] = []

    # Pass 1 - fold fits and mean-based gates (TD / FG / RARE).
    for season in validation_seasons:
        train, valid = folds_split[season]
        train_seasons = sorted({int(r["season"]) for r in train})
        if len(train_seasons) < 2:
            # Amendment 2 section 2.5 fail-closed, raised before any fit
            # or scoring touches this fold: no inner fold can form, and
            # there is no fallback to validation data, ever.
            raise NotRunError(
                f"SIGMA_SELECTION_NO_INNER_FOLD:{season}: training window "
                f"seasons {train_seasons} cannot form an inner fold "
                "- attempt NOT_RUN (pre-scoring abort, Amendment 2 "
                "section 2.5 fail-closed)")
        bundle = fit_fold_bundle(train, config)
        fold_bundles[season] = bundle
        try:
            fold_sigma, fold_sigma_detail = select_sigma_nested_v2(
                train, bundle)
        except ScoreCountsG2V2Error as exc:
            if str(exc).startswith("SIGMA_SELECTION"):
                raise NotRunError(
                    f"{exc} - attempt NOT_RUN (pre-scoring abort, "
                    "Amendment 2 section 2.5 fail-closed)") from exc
            raise
        sigma_by_fold[season] = fold_sigma
        sigma_selection[season] = fold_sigma_detail
        eval_rates, train_rates = fold_rare_rates(bundle, train, valid)
        full_map = _rate_lookup(valid, eval_rates)
        train_map = _rate_lookup(train, train_rates)
        period_maps: dict[int, dict[tuple[str, str], tuple[float, float]]] = {}
        period_train_maps: dict[int, dict[tuple[str, str], tuple[float, float]]] = {}
        for q in (1, 2, 3, 4):
            ev_q, tr_q = fold_rare_rates(
                bundle, train, valid,
                def_field=f"q{q}_def_td", saf_field=f"q{q}_safeties")
            period_maps[q] = _rate_lookup(valid, ev_q)
            period_train_maps[q] = _rate_lookup(train, tr_q)
        fold_rate_maps[season] = {
            "full": full_map, "train_full": train_map,
            "period": period_maps, "period_train": period_train_maps,
        }
        fold_meta[season] = {
            "validation_season": season,
            "training_seasons": sorted({int(r["season"]) for r in train}),
            "n_team_rows": len(valid),
            "n_games": len(game_pairs(valid)),
            "td_alpha": bundle["td_alpha"],
            "fg_opportunity_alpha": bundle["fg_alpha"],
            "thetas": {k: str(v) for k, v in bundle["thetas"].items()},
            "rare_prior": str(bundle["rare_prior"]),
            "sigma": fold_sigma,
        }
        for target, kind, store in (
            ("offense_touchdowns", "td", td_folds),
            ("made_field_goals", "fg", fg_folds),
        ):
            scored = valid
            if kind == "fg":
                # ZERO_MODEL_ROW rows (no league band context yet) cannot
                # be priced by the banded construction: excluded + counted.
                scored = [r for r in valid if row_has_band_context(r, config)]
                zero_model_counts["fg_gate_rows"] += len(valid) - len(scored)
            y = np.asarray([float(r[target]) for r in scored], dtype=float)
            if kind == "td":
                cand = np.asarray(
                    [heritage_predict_mean(bundle["td_model"], r) for r in scored],
                    dtype=float)
            else:
                cand = np.asarray(
                    [banded_made_fg_mean(bundle["fg_opportunity_model"], r, config)
                     for r in scored], dtype=float)
            base_mean = max(float(np.mean([float(r[target]) for r in train])), 1e-12)
            base = np.full_like(y, base_mean)
            cand_dev = poisson_deviance(y, cand)
            base_dev = poisson_deviance(y, base)
            store.append({
                "validation_season": season, "n_team_rows": len(scored),
                "candidate_poisson_deviance": cand_dev,
                "intercept_baseline_poisson_deviance": base_dev,
                "fold_win": bool(cand_dev < base_dev),
                "y": y, "cand": cand, "base": base,
            })
        train_rare_mean = float(np.mean(
            [float(r["def_st_touchdowns"]) + float(r["safeties"]) for r in train]))
        fold_excl = {"attempts_missing_distance": 0, "makes_missing_distance": 0}
        fold_band = {
            "realized_attempts": [0] * 5, "realized_makes": [0] * 5,
            "expected_attempts": [0.0] * 5, "expected_makes": [0.0] * 5,
            "expected_opportunity_total": 0.0, "n_team_rows": 0,
        }
        for r in valid:
            y = float(r["def_st_touchdowns"]) + float(r["safeties"])
            d_rate, s_rate = full_map[(str(r["game_id"]), str(r["team"]))]
            rare_candidate_ll += poisson_logpmf(y, d_rate + s_rate)
            rare_baseline_ll += poisson_logpmf(y, max(train_rare_mean, 1e-12))
            rare_n += 1
            fold_excl["attempts_missing_distance"] += int(r["fg_attempts_missing_distance"])
            fold_excl["makes_missing_distance"] += int(r["fg_makes_missing_distance"])
            detail = banded_made_fg_detail(bundle["fg_opportunity_model"], r, config)
            fold_band["expected_opportunity_total"] += detail["opportunity_mean"]
            fold_band["n_team_rows"] += 1
            for b in range(5):
                fold_band["realized_attempts"][b] += int(r["fg_att_band"][b])
                fold_band["realized_makes"][b] += int(r["fg_made_band"][b])
                fold_band["expected_attempts"][b] += detail["bands"][b]["expected_attempts"]
                fold_band["expected_makes"][b] += detail["bands"][b]["expected_makes"]
        fg_exclusions["attempts_missing_distance"] += fold_excl["attempts_missing_distance"]
        fg_exclusions["makes_missing_distance"] += fold_excl["makes_missing_distance"]
        fg_exclusions_by_fold.append({"validation_season": season, **fold_excl})
        for key in band_pooled:
            if isinstance(band_pooled[key], list):
                band_pooled[key] = [a + b for a, b in zip(band_pooled[key], fold_band[key])]
            else:
                band_pooled[key] += fold_band[key]
        band_folds.append({"validation_season": season, **fold_band})

    # Pass 1.5 - K3 estimation per fold, TRAINING games only. This completes
    # for every fold before any evaluation game is simulated.
    k3_folds: dict[int, Any] = {}
    if config.k3_enabled:
        for season in validation_seasons:
            train, _valid = folds_split[season]
            bundle = fold_bundles[season]
            sigma = sigma_by_fold[season]
            train_map = fold_rate_maps[season]["train_full"]
            skeleton_pmfs: list[dict[tuple[int, int], float]] = []
            realized_margins: list[int] = []
            for gid, (home, away) in sorted(game_pairs(train).items()):
                if not (row_has_band_context(home, config)
                        and row_has_band_context(away, config)):
                    # ZERO_MODEL_ROW games cannot be simulated; excluded
                    # from lambda estimation entirely (counted).
                    zero_model_counts["k3_training_games"] += 1
                    continue
                sim = simulate_full_game_v2(
                    bundle, game_id=gid, home_row=home, away_row=away,
                    home_rates=train_map[(gid, str(home["team"]))],
                    away_rates=train_map[(gid, str(away["team"]))],
                    sigma=sigma, paths=paths)
                counts = pmf_counts(sim["home_score"], sim["away_score"])
                skeleton_pmfs.append(pmf_from_counts(counts, paths))
                realized_margins.append(
                    realized_final_score(home) - realized_final_score(away))
            k3 = estimate_k3_lambdas(skeleton_pmfs, realized_margins)
            bundle["k3"] = k3
            k3_folds[season] = {
                "lambdas": {str(k): v for k, v in k3["lambdas"].items()},
                "detail": k3["detail"],
                "n_training_games": k3["n_training_games"],
                "estimation_scope": "TRAINING_GAMES_ONLY",
            }

    # Pass 2 - simulation-based gates (JOINT / CAL / KEY / PERIOD).
    period_families = ("FIRST_HALF", "SECOND_HALF", "QUARTER")
    joint_folds: list[dict[str, Any]] = []
    period_scores: dict[str, dict[int, dict[str, float]]] = {f: {} for f in period_families}
    period_baselines: dict[str, dict[int, dict[str, float]]] = {f: {} for f in period_families}
    total_pits: list[float] = []
    margin_pits: list[float] = []
    key_model_mass = {k: [] for k in K3_KEYS}
    key_skeleton_mass = {k: [] for k in K3_KEYS}
    key_realized: list[int] = []

    for season in validation_seasons:
        bundle = fold_bundles[season]
        sigma = sigma_by_fold[season]
        train, valid = folds_split[season]
        maps = fold_rate_maps[season]
        train_pairs = game_pairs(train)
        valid_pairs = game_pairs(valid)

        base_counts: dict[tuple[int, int], int] = {}
        for home, away in train_pairs.values():
            key = (realized_final_score(home), realized_final_score(away))
            base_counts[key] = base_counts.get(key, 0) + 1
        base_total = sum(base_counts.values())
        base_period: dict[str, dict[tuple[int, int], int]] = {f: {} for f in period_families}
        base_period_total: dict[str, int] = {f: 0 for f in period_families}
        for home, away in train_pairs.values():
            for fam in period_families:
                if fam == "QUARTER":
                    realized = [((int(home[f"q{q}_points"]), int(away[f"q{q}_points"])))
                                 for q in (1, 2, 3, 4)]
                elif fam == "FIRST_HALF":
                    realized = [(int(home["q1_points"]) + int(home["q2_points"]),
                                 int(away["q1_points"]) + int(away["q2_points"]))]
                else:
                    realized = [(int(home["q3_points"]) + int(home["q4_points"]),
                                 int(away["q3_points"]) + int(away["q4_points"]))]
                for pair_key in realized:
                    base_period[fam][pair_key] = base_period[fam].get(pair_key, 0) + 1
                    base_period_total[fam] += 1

        cand_joint = 0.0
        base_joint = 0.0
        prime_joint = 0.0
        fam_cand: dict[str, list[float]] = {f: [] for f in period_families}
        fam_base: dict[str, list[float]] = {f: [] for f in period_families}
        lambdas = bundle["k3"]["lambdas"] if config.k3_enabled else None

        scored_games = 0
        for gid, (home, away) in sorted(valid_pairs.items()):
            if not (row_has_band_context(home, config)
                    and row_has_band_context(away, config)):
                zero_model_counts["validation_games"] += 1
                continue
            scored_games += 1
            realized = (realized_final_score(home), realized_final_score(away))
            sim = simulate_full_game_v2(
                bundle, game_id=gid, home_row=home, away_row=away,
                home_rates=maps["full"][(gid, str(home["team"]))],
                away_rates=maps["full"][(gid, str(away["team"]))],
                sigma=sigma, paths=paths)
            counts = pmf_counts(sim["home_score"], sim["away_score"])
            skeleton_pmf = pmf_from_counts(counts, paths)
            candidate_pmf = apply_k3(skeleton_pmf, lambdas) if lambdas else skeleton_pmf
            cand_joint += log_score_pmf(candidate_pmf, realized, paths)
            base_joint += log_score(base_counts, base_total, realized, paths)
            prime_pmf = independent_marginals_pmf(candidate_pmf)
            prime_joint += log_score_pmf(prime_pmf, realized, paths)

            cal_rng = rng_for_v2(gid, "CAL")
            total_law: dict[int, float] = {}
            for (h, a), p in candidate_pmf.items():
                total_law[h + a] = total_law.get(h + a, 0.0) + p
            m_law = margin_law(candidate_pmf)
            total_pits.append(randomized_pit_from_law(total_law, sum(realized), cal_rng))
            margin_pits.append(randomized_pit_from_law(
                m_law, realized[0] - realized[1], cal_rng))
            skel_law = margin_law(skeleton_pmf)
            for k in K3_KEYS:
                key_model_mass[k].append(float(m_law.get(k, 0.0)))
                key_skeleton_mass[k].append(float(skel_law.get(k, 0.0)))
            key_realized.append(realized[0] - realized[1])

            home_period = {q: maps["period"][q][(gid, str(home["team"]))] for q in (1, 2, 3, 4)}
            away_period = {q: maps["period"][q][(gid, str(away["team"]))] for q in (1, 2, 3, 4)}
            psim = simulate_period_game_v2(
                bundle, game_id=gid, home_row=home, away_row=away,
                home_period_rates=home_period, away_period_rates=away_period,
                sigma=sigma, paths=paths)
            fam_pairs: dict[str, list[tuple[Any, Any, tuple[int, int]]]] = {
                "FIRST_HALF": [(psim["first_half_home"], psim["first_half_away"],
                                (int(home["q1_points"]) + int(home["q2_points"]),
                                 int(away["q1_points"]) + int(away["q2_points"])))],
                "SECOND_HALF": [(psim["second_half_home"], psim["second_half_away"],
                                 (int(home["q3_points"]) + int(home["q4_points"]),
                                  int(away["q3_points"]) + int(away["q4_points"])))],
                "QUARTER": [
                    (psim["home_points"][q], psim["away_points"][q],
                     (int(home[f"q{q}_points"]), int(away[f"q{q}_points"])))
                    for q in (1, 2, 3, 4)
                ],
            }
            for fam in period_families:
                for h_arr, a_arr, realized_pair in fam_pairs[fam]:
                    pc = pmf_counts(h_arr, a_arr)
                    fam_cand[fam].append(log_score(pc, paths, realized_pair, paths))
                    fam_base[fam].append(log_score(
                        base_period[fam], base_period_total[fam], realized_pair, paths))

        n_games = scored_games
        joint_folds.append({
            "validation_season": season,
            "n_games": n_games,
            "candidate_mean_log_score": cand_joint / n_games,
            "baseline_i_mean_log_score": base_joint / n_games,
            "baseline_ii_prime_mean_log_score": prime_joint / n_games,
            "fold_win_vs_baseline_i": bool(cand_joint > base_joint),
            "fold_win_vs_baseline_ii_prime": bool(cand_joint > prime_joint),
        })
        for fam in period_families:
            period_scores[fam][season] = {
                "candidate_mean_log_score": float(np.mean(fam_cand[fam])) if fam_cand[fam] else 0.0,
                "n": len(fam_cand[fam]),
            }
            period_baselines[fam][season] = {
                "baseline_mean_log_score": float(np.mean(fam_base[fam])) if fam_base[fam] else 0.0,
                "n": len(fam_base[fam]),
            }

    g_td = assemble_count_gate(td_folds)
    g_fg = assemble_count_gate(fg_folds)
    g_rare = assemble_rare_gate(rare_candidate_ll, rare_baseline_ll, rare_n)
    g_joint = assemble_joint_gate(joint_folds)
    g_cal = assemble_cal_gate(total_pits, margin_pits)
    g_key = assemble_key_gate(key_model_mass, key_skeleton_mass, key_realized)
    g_period = assemble_period_gate(
        period_scores, period_baselines, validation_seasons=validation_seasons)

    full_game_pass = bool(
        g_td["pass"] and g_fg["pass"] and g_rare["pass"]
        and g_joint["pass"] and g_cal["pass"] and g_key["pass"]
    )
    return {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G2_DEVELOPMENT_GATE_V1",
        "attempt_number": ATTEMPT_NUMBER,
        "label": "DEVELOPMENT — already-exposed 2018-2025 window; NOT forward evidence",
        "validation_seasons": list(validation_seasons),
        "all_targets_must_pass": True,
        "sigma_by_fold": {str(s): sigma_by_fold[s] for s in validation_seasons},
        "sigma_selection": {str(s): sigma_selection[s] for s in validation_seasons},
        "sigma_selection_rule": "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY",
        "fold_meta": [fold_meta[s] for s in validation_seasons],
        "k3_folds": {str(s): k3_folds[s] for s in validation_seasons} if config.k3_enabled else {},
        "gates": {
            "G_TD": g_td,
            "G_FG": g_fg,
            "G_RARE": g_rare,
            "G_JOINT": g_joint,
            "G_CAL": g_cal,
            "G_KEY": g_key,
            "G_PERIOD": g_period,
        },
        "fg_exclusions": fg_exclusions,
        "fg_exclusions_by_fold": fg_exclusions_by_fold,
        "zero_model_row_exclusions": zero_model_counts,
        "fg_band_detail": {
            "bands": ["0-29", "30-39", "40-49", "50-59", "60+"],
            "construction": (
                "Realized counts are the validation rows' distance-evidenced FG "
                "attempts/makes per band. Expected attempts per band = fold "
                "opportunity mean x PIT band share (attempt 2: decayed-PIT "
                "shares/rates, section 2.3); expected makes = expected attempts "
                "x band conversion rate. Opportunity and conversion are reported "
                "separately; no gate consumes this table."
            ),
            "pooled": band_pooled,
            "folds": band_folds,
        },
        "full_game_pass": full_game_pass,
        "market_data_used": False,
    }


# ---------------------------------------------------------------------------
# Result record + fit artifact writers (attempt-1 shapes, attempt-2 fields).
# Writing a real result record is execution; these writers exist for the
# governed path and are exercised by tests only on synthetic records.
# ---------------------------------------------------------------------------

def build_attempt2_result_record(
    *,
    evaluation: Mapping[str, Any] | None,
    status: str,
    attempt_consumed: bool,
    reason: str | None = None,
    preregistration_sha256: str | None = None,
    preregistration_commit_sha: str | None = None,
    code_identity_sha256: str | None = None,
    source_manifest_sha256: str | None = None,
    training_team_rows: int | None = None,
    runner_provenance: Mapping[str, Any] | None = None,
    schedule_score_cross_check: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    passing: list[str] = []
    failing: list[str] = []
    period_results: dict[str, Any] = {}
    if evaluation is not None:
        gates = evaluation["gates"]
        for name in ("G_TD", "G_FG", "G_RARE", "G_JOINT", "G_CAL", "G_KEY"):
            (passing if gates[name]["pass"] else failing).append(name)
        period_results = {
            fam: {"pass": detail["pass"]}
            for fam, detail in gates["G_PERIOD"].items()
        }
    record: dict[str, Any] = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G2_ATTEMPT_RESULT_V1",
        "family": "NFL_SCORE_COUNTS_G2",
        "attempt_number": ATTEMPT_NUMBER,
        "attempt_budget": ATTEMPT_BUDGET,
        "attempt_consumed": bool(attempt_consumed),
        "attempts_remaining_after_this_result": (
            ATTEMPT_BUDGET - ATTEMPTS_CONSUMED_BEFORE - (1 if attempt_consumed else 0)),
        "status": status,
        "authority": dict(AUTHORITY),
        "preregistration_commit_sha": preregistration_commit_sha,
        "preregistration_sha256": preregistration_sha256,
        "code_identity_sha256": code_identity_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "training_team_rows": training_team_rows,
        "evaluation": dict(evaluation) if evaluation is not None else None,
        "passing_gates": passing,
        "failing_gates": failing,
        "period_gate_results": period_results,
        "runner_provenance": dict(runner_provenance) if runner_provenance else None,
        "schedule_score_cross_check": (
            dict(schedule_score_cross_check) if schedule_score_cross_check else None),
        "market_data_used": False,
    }
    if reason is not None:
        record["reason"] = reason
    return record


def not_run_record(reason: str, **identity: Any) -> dict[str, Any]:
    """Pre-scoring NOT_RUN: attempt not consumed, no gate evaluated."""
    return build_attempt2_result_record(
        evaluation=None, status="NOT_RUN", attempt_consumed=False,
        reason=reason, **identity)


def write_result_record(record: Mapping[str, Any], path: Any) -> str:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    p.write_text(payload, encoding="utf-8")
    return sha256(payload.encode("utf-8")).hexdigest()


def build_attempt2_fit_artifact(
    rows: Sequence[Mapping[str, Any]],
    *,
    evaluation: Mapping[str, Any],
    source_manifest_sha256: str,
    code_identity: str,
    preregistration_sha256: str,
    config: ModelFormConfig = V2_CONFIG,
    paths: int = PATHS_PER_GAME,
) -> dict[str, Any]:
    """Development fit artifact mirroring attempt-1's shape, refit on the
    full development window, with the attempt-2 selections recorded."""
    from dataclasses import asdict
    rows = list(rows)
    bundle = fit_fold_bundle(rows, config)
    # The artifact's own window is the full development window as training;
    # its sigma is selected by the same Amendment 2 nested rule inside
    # that window. The evaluation's per-fold sigmas are recorded below.
    sigma, _sigma_detail = select_sigma_nested_v2(rows, bundle)
    pairs = game_pairs(rows)
    n = len(rows)
    def_rate = float(np.mean([float(r["def_st_touchdowns"]) for r in rows]))
    safety_rate = float(np.mean([float(r["safeties"]) for r in rows]))
    pat = sum(float(r["pat_made"]) for r in rows)
    two = sum(float(r["two_point_made"]) for r in rows)
    no = sum(float(r["no_conversion"]) for r in rows)
    total_conv = pat + two + no
    conv = (pat / total_conv, two / total_conv, no / total_conv)

    k3_record = None
    if config.k3_enabled:
        _ev, train_rates = fold_rare_rates(bundle, rows, [])
        train_map = _rate_lookup(rows, train_rates)
        skeleton_pmfs: list[dict[tuple[int, int], float]] = []
        realized_margins: list[int] = []
        for gid, (home, away) in sorted(pairs.items()):
            if not (row_has_band_context(home, config)
                    and row_has_band_context(away, config)):
                continue  # ZERO_MODEL_ROW: excluded from estimation
            sim = simulate_full_game_v2(
                bundle, game_id=gid, home_row=home, away_row=away,
                home_rates=train_map[(gid, str(home["team"]))],
                away_rates=train_map[(gid, str(away["team"]))],
                sigma=sigma, paths=paths)
            counts = pmf_counts(sim["home_score"], sim["away_score"])
            skeleton_pmfs.append(pmf_from_counts(counts, paths))
            realized_margins.append(
                realized_final_score(home) - realized_final_score(away))
        k3 = estimate_k3_lambdas(skeleton_pmfs, realized_margins)
        bundle["k3"] = k3
        k3_record = {
            "lambdas": {str(k): v for k, v in k3["lambdas"].items()},
            "detail": k3["detail"],
            "n_training_games": k3["n_training_games"],
            "estimation_scope": "FULL_DEVELOPMENT_WINDOW_AS_TRAINING",
        }

    artifact: dict[str, Any] = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G2_ATTEMPT_FIT_V1",
        "family": "NFL_SCORE_COUNTS_G2",
        "attempt_number": ATTEMPT_NUMBER,
        "status": (
            "DEVELOPMENT_ATTEMPT_PASS" if evaluation["full_game_pass"]
            else "DEVELOPMENT_ATTEMPT_FAIL"
        ),
        "fit_window": {
            "seasons": sorted({int(r["season"]) for r in rows}),
            "team_row_count": n,
            "game_count": len(pairs),
        },
        "preregistration_sha256": preregistration_sha256,
        "code_identity": code_identity,
        "source_manifest_sha256": source_manifest_sha256,
        "rng_identity": {
            "bit_generator": "NUMPY_PCG64",
            "root_seed_literal": ROOT_SEED_LITERAL_V2,
            "root_seed_sha256": ROOT_SEED_SHA256_V2,
            "paths_per_game": PATHS_PER_GAME,
        },
        "sigma": float(sigma),
        "sigma_by_fold": dict(evaluation["sigma_by_fold"]),
        "sigma_selection_rule": "AMENDMENT_2_NESTED_TRAINING_WINDOW_ONLY",
        "td_model": asdict(bundle["td_model"]),
        "fg_opportunity_model": asdict(bundle["fg_opportunity_model"]),
        "period_models": {
            str(q): {
                "td_model": asdict(bundle["period"][q]["td_model"]),
                "fg_model": asdict(bundle["period"][q]["fg_model"]),
            }
            for q in (1, 2, 3, 4)
        },
        "thetas": {k: str(v) for k, v in bundle["thetas"].items()},
        "rare_prior_selection": {
            "selected": str(bundle["rare_prior"]),
            "cv_scores": bundle["rare_cv_scores"],
        },
        "k3": k3_record,
        "league_priors": {
            "def_st_td_rate": def_rate,
            "safety_rate": safety_rate,
            "conversion_probabilities": [float(v) for v in conv],
        },
        "development_gate": dict(evaluation),
        "fg_detail_sample": {
            "construction": "made_fg_mean = opportunity_mean * SUM_b(share_b * rate_b), bands 0-29/30-39/40-49/50-59/60+, EB prior 25 attempts, attempt 2: decayed-PIT shares/rates (0.85 recursion)",
        },
        "authority": dict(AUTHORITY),
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("utf-8")
    artifact["artifact_sha256"] = sha256(canonical).hexdigest()
    return artifact


__all__ = [
    "RARE_TOLERANCE", "CAL_SLOPE_BOUNDS", "CAL_MARGIN_DEV_BOUND",
    "KEY_ABS_BOUND", "MIN_FOLD_WINS", "FOLD_MIN_GAMES",
    "ATTEMPT_BUDGET", "ATTEMPTS_CONSUMED_BEFORE", "AUTHORITY",
    "DISCRETE_V2_LEG", "NotRunError", "fail_gate",
    "randomized_pit_from_law",
    "assemble_count_gate", "assemble_rare_gate", "assemble_joint_gate",
    "assemble_cal_gate", "assemble_key_gate", "assemble_period_gate",
    "run_development_evaluation_v2",
    "build_attempt2_result_record", "not_run_record", "write_result_record",
    "build_attempt2_fit_artifact",
]
