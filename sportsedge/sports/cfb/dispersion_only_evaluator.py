"""Governed CFB dispersion-only diagnostic evaluator.

Consumes only the frozen V3 winner capture plus the hash-bound materialized rows.
Performs no mean-model refitting and has zero promotion / betting authority.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence
import numpy as np

from .candidate_bakeoff import _hash
from .joint_model_v2_challenger import MIN_OOF_RESIDUAL_PAIRS, _fit_scale

EVALUATOR_ID = "CFB_DISPERSION_ONLY_EVALUATOR_V1"
SCORING_SEASONS = tuple(range(2019, 2026))
RESIDUAL_SEED_SEASON = 2018
N_PATHS = 5000
BASE_SEED = 20260925
BOOTSTRAP_SEED = 20260926
PIT_SEED = 20260927
BOOTSTRAP_RESAMPLES = 2000
KEY_MARGINS = (3, 7)


class CFBDispersionEvaluationError(ValueError):
    pass


def _rid(row: Mapping[str, Any]) -> tuple[int, int, str]:
    try:
        return int(row["season"]), int(row["week"]), str(row["game_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_ROW_IDENTITY_REQUIRED") from exc


def _integer_score(value: Any, name: str) -> int:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBDispersionEvaluationError(f"CFB_DISPERSION_SCORE_INVALID:{name}") from exc
    if not np.isfinite(x) or x < 0 or not x.is_integer():
        raise CFBDispersionEvaluationError(f"CFB_DISPERSION_SCORE_INVALID:{name}")
    return int(x)


def _verify_embedded_hash(payload: Mapping[str, Any], field: str, error: str) -> str:
    body = dict(payload)
    claimed = str(body.pop(field, ""))
    if not claimed or _hash(body) != claimed:
        raise CFBDispersionEvaluationError(error)
    return claimed


def _zero_authority(payload: Mapping[str, Any], error: str) -> None:
    authority = payload.get("authority")
    if not isinstance(authority, Mapping) or any(v is not False for v in authority.values()):
        raise CFBDispersionEvaluationError(error)


def _validate_inputs(
    rows: Sequence[Mapping[str, Any]],
    bakeoff_result: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Mapping[str, Any], dict[int, Mapping[str, Any]], str, str]:
    data = [dict(r) for r in rows]
    if not data or _hash(data) != bakeoff_result.get("rows_sha256"):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_PARENT_ROWS_HASH_MISMATCH")
    result_sha = _verify_embedded_hash(
        bakeoff_result, "result_sha256", "CFB_DISPERSION_BAKEOFF_RESULT_HASH_INVALID"
    )
    capture_sha = _verify_embedded_hash(
        capture, "capture_sha256", "CFB_DISPERSION_CAPTURE_HASH_INVALID"
    )
    _zero_authority(bakeoff_result, "CFB_DISPERSION_BAKEOFF_AUTHORITY_INVALID")
    _zero_authority(capture, "CFB_DISPERSION_CAPTURE_AUTHORITY_INVALID")
    if bakeoff_result.get("status") != "WINNER_SELECTED_FOR_FREEZE":
        raise CFBDispersionEvaluationError("CFB_DISPERSION_PARENT_WINNER_REQUIRED")
    if capture.get("status") != "WINNER_CAPTURE_RETAINED":
        raise CFBDispersionEvaluationError("CFB_DISPERSION_WINNER_CAPTURE_REQUIRED")
    winner = str(bakeoff_result.get("winner") or "")
    wc = capture.get("winner_capture")
    if not winner or capture.get("retained_family") != winner or not isinstance(wc, Mapping) or wc.get("family") != winner:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_WINNER_CAPTURE_MISMATCH")
    folds_raw = wc.get("folds")
    if not isinstance(folds_raw, list):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_FOLDS_REQUIRED")
    folds: dict[int, Mapping[str, Any]] = {}
    for fold in folds_raw:
        if not isinstance(fold, Mapping):
            raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_FOLD_INVALID")
        season = int(fold.get("outer_season", -1))
        if season in folds:
            raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_FOLD_DUPLICATE")
        folds[season] = fold
    if set(folds) != set(range(2018, 2026)):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_FOLD_WINDOW_INVALID")

    ordered_ids = [_rid(r) for r in data]
    if len(set(ordered_ids)) != len(ordered_ids):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_PARENT_ROW_ID_DUPLICATE")
    for season, fold in folds.items():
        expected_outer = [rid for rid in ordered_ids if rid[0] == season]
        expected_train = [rid for rid in ordered_ids if rid[0] < season]
        outer = fold.get("outer_predictions")
        train = fold.get("training_residuals")
        if not isinstance(outer, list) or not isinstance(train, list):
            raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_ROWS_REQUIRED")
        if [_rid(r) for r in outer] != expected_outer or [_rid(r) for r in train] != expected_train:
            raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_ROW_SET_MISMATCH")
        row_map = {_rid(r): r for r in data}
        for p in outer:
            raw = row_map[_rid(p)]
            if float(p["realized_home_score"]) != float(raw["home_score"]) or float(p["realized_away_score"]) != float(raw["away_score"]):
                raise CFBDispersionEvaluationError("CFB_DISPERSION_CAPTURE_REALIZED_SCORE_MISMATCH")
    return data, wc, folds, result_sha, capture_sha


def _overtime_profile(rows: Sequence[Mapping[str, Any]], season: int) -> np.ndarray:
    out: list[tuple[int, int]] = []
    for r in rows:
        if int(r["season"]) >= season:
            continue
        if "regulation_home_score" not in r or "regulation_away_score" not in r:
            continue
        rh = _integer_score(r["regulation_home_score"], "regulation_home_score")
        ra = _integer_score(r["regulation_away_score"], "regulation_away_score")
        fh = _integer_score(r["home_score"], "home_score")
        fa = _integer_score(r["away_score"], "away_score")
        if rh == ra and fh != fa:
            dh, da = fh - rh, fa - ra
            if dh < 0 or da < 0 or dh == da:
                raise CFBDispersionEvaluationError("CFB_DISPERSION_OVERTIME_DELTA_INVALID")
            out.append((dh, da))
    return np.asarray(out, dtype=int).reshape((-1, 2)) if out else np.empty((0, 2), dtype=int)


def _resolve_ties(h: np.ndarray, a: np.ndarray, rng: np.random.Generator, ot: np.ndarray) -> None:
    ties = np.flatnonzero(h == a)
    if not ties.size:
        return
    if ot.size == 0:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_OVERTIME_PROFILE_REQUIRED")
    pick = rng.integers(0, len(ot), size=ties.size)
    h[ties] += ot[pick, 0]
    a[ties] += ot[pick, 1]
    if np.any(h == a):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_OVERTIME_PROFILE_DID_NOT_RESOLVE_TIE")


def simulate_v1_capture_paths(
    mean_home: float,
    mean_away: float,
    residual_pairs: np.ndarray,
    overtime_deltas: np.ndarray,
    *,
    seed: int,
    n_paths: int,
) -> tuple[np.ndarray, np.ndarray]:
    if residual_pairs.ndim != 2 or residual_pairs.shape[1] != 2 or len(residual_pairs) == 0:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_V1_RESIDUALS_INVALID")
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(residual_pairs), size=int(n_paths))
    h = np.maximum(0, np.rint(float(mean_home) + residual_pairs[idx, 0])).astype(int)
    a = np.maximum(0, np.rint(float(mean_away) + residual_pairs[idx, 1])).astype(int)
    _resolve_ties(h, a, rng, overtime_deltas)
    return h, a


def build_v2_capture_state(folds: Mapping[int, Mapping[str, Any]], scored_season: int):
    mus_h: list[float] = []
    mus_a: list[float] = []
    res_h: list[float] = []
    res_a: list[float] = []
    for season in range(RESIDUAL_SEED_SEASON, scored_season):
        fold = folds.get(season)
        if fold is None:
            raise CFBDispersionEvaluationError("CFB_DISPERSION_V2_SEED_FOLD_MISSING")
        for p in fold["outer_predictions"]:
            mh, ma = float(p["predicted_home_score"]), float(p["predicted_away_score"])
            mus_h.append(mh); mus_a.append(ma)
            res_h.append(float(p["realized_home_score"]) - mh)
            res_a.append(float(p["realized_away_score"]) - ma)
    if len(res_h) < MIN_OOF_RESIDUAL_PAIRS:
        raise CFBDispersionEvaluationError(f"CFB_DISPERSION_V2_OOF_RESIDUALS_INSUFFICIENT:{len(res_h)}")
    mh, ma = np.asarray(mus_h), np.asarray(mus_a)
    rh, ra = np.asarray(res_h), np.asarray(res_a)
    hs, as_ = _fit_scale(mh, rh), _fit_scale(ma, ra)
    pairs = np.column_stack((rh / hs.at(mh), ra / as_.at(ma)))
    if not np.all(np.isfinite(pairs)):
        raise CFBDispersionEvaluationError("CFB_DISPERSION_V2_STANDARDIZED_RESIDUAL_NONFINITE")
    return hs, as_, pairs


def simulate_v2_capture_paths(
    mean_home: float,
    mean_away: float,
    state,
    overtime_deltas: np.ndarray,
    *,
    seed: int,
    n_paths: int,
) -> tuple[np.ndarray, np.ndarray]:
    hs, as_, pairs = state
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(pairs), size=int(n_paths))
    h = np.maximum(0, np.rint(float(mean_home) + pairs[idx, 0] * hs.at(float(mean_home)))).astype(int)
    a = np.maximum(0, np.rint(float(mean_away) + pairs[idx, 1] * as_.at(float(mean_away)))).astype(int)
    _resolve_ties(h, a, rng, overtime_deltas)
    return h, a


def ranked_probability_score(sim: np.ndarray, actual: int) -> float:
    if sim.ndim != 1 or sim.size == 0:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_RPS_SIM_INVALID")
    lo, hi = min(int(np.min(sim)), int(actual)), max(int(np.max(sim)), int(actual))
    support = np.arange(lo, hi + 1, dtype=int)
    ordered = np.sort(sim.astype(int, copy=False))
    cdf = np.searchsorted(ordered, support, side="right") / float(len(ordered))
    observed = (int(actual) <= support).astype(float)
    return float(np.sum((cdf - observed) ** 2))


def _pit(sim: np.ndarray, actual: int, u: float) -> float:
    return float(np.mean(sim < actual) + u * np.mean(sim == actual))


def _coverage(values: Sequence[float]) -> dict[str, float]:
    p = np.asarray(values, dtype=float)
    return {f"cover_{int(c*100)}": float(np.mean(np.abs(p - 0.5) <= c / 2.0)) for c in (0.5, 0.8, 0.95)}


def _bootstrap_ci(game_rows: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    grouped: dict[tuple[int, int], list[float]] = defaultdict(list)
    for row in game_rows:
        grouped[(int(row["season"]), int(row["week"]))].append(float(row["rps_diff_v1_minus_v2"]))
    keys = sorted(grouped)
    if not keys:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_BOOTSTRAP_CLUSTERS_EMPTY")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)
    for i in range(BOOTSTRAP_RESAMPLES):
        picks = rng.integers(0, len(keys), size=len(keys))
        vals = [v for j in picks for v in grouped[keys[int(j)]]]
        means[i] = float(np.mean(vals))
    q = np.quantile(means, [0.025, 0.975], method="linear")
    return float(q[0]), float(q[1])


def evaluate_cfb_dispersion_only(
    rows: Sequence[Mapping[str, Any]],
    bakeoff_result: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    data, wc, folds, result_sha, capture_sha = _validate_inputs(rows, bakeoff_result, capture)
    scored = [r for r in data if int(r["season"]) in SCORING_SEASONS]
    scored_ids = [_rid(r) for r in scored]
    expected = [rid for rid in [_rid(r) for r in data] if rid[0] in SCORING_SEASONS]
    if scored_ids != expected:
        raise CFBDispersionEvaluationError("CFB_DISPERSION_SCORED_ROWS_NOT_EXACT_PARENT_SET")

    fold_outer = {s: {_rid(p): p for p in folds[s]["outer_predictions"]} for s in SCORING_SEASONS}
    v1_resid = {
        s: np.asarray([(float(p["home_residual"]), float(p["away_residual"])) for p in folds[s]["training_residuals"]], dtype=float)
        for s in SCORING_SEASONS
    }
    v2_state = {s: build_v2_capture_state(folds, s) for s in SCORING_SEASONS}
    overtime = {s: _overtime_profile(data, s) for s in SCORING_SEASONS}

    game_scores: list[dict[str, Any]] = []
    pit_rng = np.random.default_rng(PIT_SEED)
    pits = {m: {t: [] for t in ("margin", "total")} for m in ("v1", "v2")}
    predicted_totals: list[float] = []
    key_counts = {m: {k: 0 for k in KEY_MARGINS} for m in ("v1", "v2")}
    realized_key = {k: 0 for k in KEY_MARGINS}

    for index, raw in enumerate(scored):
        season, week, _ = _rid(raw)
        pred = fold_outer[season].get(_rid(raw))
        if pred is None:
            raise CFBDispersionEvaluationError("CFB_DISPERSION_REQUIRED_ROW_UNSCORABLE")
        mh, ma = float(pred["predicted_home_score"]), float(pred["predicted_away_score"])
        ah, aa = _integer_score(raw["home_score"], "home_score"), _integer_score(raw["away_score"], "away_score")
        seed = BASE_SEED + index
        h1, a1 = simulate_v1_capture_paths(mh, ma, v1_resid[season], overtime[season], seed=seed, n_paths=N_PATHS)
        h2, a2 = simulate_v2_capture_paths(mh, ma, v2_state[season], overtime[season], seed=seed, n_paths=N_PATHS)
        m1, t1, m2, t2 = h1 - a1, h1 + a1, h2 - a2, h2 + a2
        actual_m, actual_t = ah - aa, ah + aa
        rps1 = 0.5 * ranked_probability_score(m1, actual_m) + 0.5 * ranked_probability_score(t1, actual_t)
        rps2 = 0.5 * ranked_probability_score(m2, actual_m) + 0.5 * ranked_probability_score(t2, actual_t)
        game_scores.append({"season": season, "week": week, "game_id": _rid(raw)[2], "v1_rps": rps1, "v2_rps": rps2, "rps_diff_v1_minus_v2": rps1-rps2})
        um, ut = float(pit_rng.random()), float(pit_rng.random())
        pits["v1"]["margin"].append(_pit(m1, actual_m, um)); pits["v2"]["margin"].append(_pit(m2, actual_m, um))
        pits["v1"]["total"].append(_pit(t1, actual_t, ut)); pits["v2"]["total"].append(_pit(t2, actual_t, ut))
        predicted_totals.append(mh + ma)
        for k in KEY_MARGINS:
            key_counts["v1"][k] += int(np.sum(np.abs(m1) == k))
            key_counts["v2"][k] += int(np.sum(np.abs(m2) == k))
            realized_key[k] += int(abs(actual_m) == k)

    v1_mean = float(np.mean([r["v1_rps"] for r in game_scores]))
    v2_mean = float(np.mean([r["v2_rps"] for r in game_scores]))
    diff = v1_mean - v2_mean
    ci_low, ci_high = _bootstrap_ci(game_scores)
    label = "V2_DEMONSTRATED_DISPERSION_IMPROVEMENT_DIAGNOSTIC_ONLY" if diff > 0 and ci_low > 0 else "NO_DEMONSTRATED_DISPERSION_IMPROVEMENT"

    totals = np.asarray(predicted_totals)
    cuts = np.quantile(totals, [1/3, 2/3], method="linear")
    tercile = np.searchsorted(cuts, totals, side="right")
    coverage = {}
    for model in ("v1", "v2"):
        coverage[model] = {"overall": {target: _coverage(pits[model][target]) for target in ("margin", "total")}, "by_predicted_total_tercile": {}}
        for group in range(3):
            idx = np.flatnonzero(tercile == group)
            coverage[model]["by_predicted_total_tercile"][str(group+1)] = {
                target: _coverage([pits[model][target][int(i)] for i in idx]) for target in ("margin", "total")
            }

    n_games = len(game_scores)
    key_diag = {}
    for k in KEY_MARGINS:
        realized = realized_key[k] / float(n_games)
        key_diag[str(k)] = {"realized": realized}
        for model in ("v1", "v2"):
            predicted = key_counts[model][k] / float(n_games * N_PATHS)
            key_diag[str(k)][model] = {"predicted": predicted, "delta_percentage_points": 100.0 * (predicted-realized), "within_1_5pp_reference": abs(predicted-realized) <= 0.015}

    counts = defaultdict(int)
    for r in scored:
        counts[f"{int(r['season'])}-W{int(r['week'])}"] += 1

    return {
        "schema": "CFB_DISPERSION_ONLY_RESULT_V1",
        "evaluator_id": EVALUATOR_ID,
        "status": label,
        "winner_family": wc["family"],
        "bakeoff_result_sha256": result_sha,
        "capture_sha256": capture_sha,
        "selection_rows_sha256": bakeoff_result["rows_sha256"],
        "scored_seasons": list(SCORING_SEASONS),
        "n_games": n_games,
        "n_paths_per_game_per_model": N_PATHS,
        "primary_metric": {
            "name": "MEAN_RANKED_PROBABILITY_SCORE_MARGIN_AND_TOTAL",
            "v1_rps": v1_mean,
            "v2_rps": v2_mean,
            "v1_minus_v2": diff,
            "cluster_bootstrap_95_ci": [ci_low, ci_high],
            "clusters": "season-week",
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "interval_method": "PERCENTILE_LINEAR_2.5_97.5",
        },
        "secondary_diagnostics_no_authority": {
            "randomized_pit_coverage": coverage,
            "predicted_total_tercile_cutpoints": [float(cuts[0]), float(cuts[1])],
            "absolute_margin_mass": key_diag,
        },
        "row_counts_by_season_week": dict(sorted(counts.items())),
        "simulation": {"seed_policy": "EXPLICIT_NUMPY_PCG64_V1", "base_seed": BASE_SEED, "pit_seed": PIT_SEED},
        "provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "classification": ["RESEARCH_ONLY", "NOT_Model_P", "NOT_Truth_Gate", "NOT_OFFICIAL"],
        "authority": {"model_p_created": False, "truth_gate_authority": False, "promotion_authority": False, "eligibility_changed": False, "staking_authority": False, "official_authority": False, "historical_pit_created": False, "backfill": False},
    }


__all__ = [
    "CFBDispersionEvaluationError", "EVALUATOR_ID", "evaluate_cfb_dispersion_only",
    "ranked_probability_score", "build_v2_capture_state", "simulate_v1_capture_paths", "simulate_v2_capture_paths",
]
