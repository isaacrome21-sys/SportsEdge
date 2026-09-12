"""NFL M2 V2E diagnostic candidate: possession-level discrete scoring model.

This module is research-only. It deliberately leaves production M2, the
promotion registry, eligibility, staking, and market pricing untouched.

V2E changes the generative architecture rather than tuning the already-observed
V2A/V2B/V2C/V2D score-regression family. Training rows contain realized
football possession counts/outcomes plus point-in-time market-blind state. The
model conditions both possession volume and per-possession scoring-event rates
on that state, then creates coherent integer home/away scores before any
sportsbook line is applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, gcd, isfinite, lgamma, log
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

NFL_M2_V2E_CANDIDATE_MODEL_ID = "nfl_m2_possession_discrete_v2e_candidate"
NFL_M2_V2E_DISTRIBUTION_CONTRACT = "NFL_M2_V2E_POSSESSION_DISCRETE_SCORE_V2"
NFL_M2_V2E_FEATURE_CONTRACT = "NFL_M2_V2E_MARKET_BLIND_DRIVE_STATE_V2"
NFL_M2_V2E_STATE_RIDGE_ALPHA = 10.0

# Frozen before first V2E outer diagnostic. These fields already come from the
# production PIT feature builder; no sportsbook value or realized current-game
# result is part of this state.
NFL_M2_V2E_PIT_STATE_FIELDS = (
    "adj_off_epa",
    "adj_def_epa",
    "pass_epa",
    "rush_epa",
    "pressure_for",
    "pressure_allowed",
    "success_rate",
    "explosive_rate",
    "qb_adjustment",
    "prior_efficiency",
    "prior_weight",
)

# Defensive touchdowns and safeties are attached to the offense's possession
# but credit points to the opponent. The defensive-TD first slice is explicitly
# seven points; PAT/2PT refinement is a later architecture question, not hidden
# inside this diagnostic.
_OUTCOMES = (
    "td_xp", "td_2pt", "td_no_try", "fg", "def_td_7_allowed",
    "safety_allowed", "no_score",
)
_OWN_POINTS = {
    "td_xp": 7,
    "td_2pt": 8,
    "td_no_try": 6,
    "fg": 3,
    "def_td_7_allowed": 0,
    "safety_allowed": 0,
    "no_score": 0,
}
_PROHIBITED_MARKET_KEYS = {
    "spread", "spread_line", "total", "total_line", "moneyline", "odds",
    "price", "implied_probability", "closing_spread", "closing_total",
    "tickets", "handle", "consensus",
}
_EPS = 1e-9


def _finite_float(value: Any, *, reason: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if not isfinite(out):
        raise ValueError(reason)
    return out


def _nonnegative_int(value: Any, *, reason: str) -> int:
    number = _finite_float(value, reason=reason)
    integer = int(number)
    if number != integer or integer < 0:
        raise ValueError(reason)
    return integer


def _assert_market_blind(row: Mapping[str, Any]) -> None:
    stack: list[Mapping[str, Any]] = [row]
    while stack:
        current = stack.pop()
        for key, value in current.items():
            if str(key).strip().lower() in _PROHIBITED_MARKET_KEYS:
                raise ValueError(f"NFL_M2_V2E_MARKET_DATA_PROHIBITED:{key}")
            if isinstance(value, Mapping):
                stack.append(value)


def _state_names(data: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    expected: tuple[str, ...] | None = None
    for row in data:
        for side in ("home", "away"):
            raw = row.get(f"{side}_state")
            if not isinstance(raw, Mapping) or not raw:
                raise ValueError("NFL_M2_V2E_PIT_STATE_REQUIRED")
            _assert_market_blind(raw)
            names = tuple(sorted(str(key) for key in raw))
            if expected is None:
                expected = names
            elif names != expected:
                raise ValueError("NFL_M2_V2E_STATE_SCHEMA_MISMATCH")
    if not expected:
        raise ValueError("NFL_M2_V2E_PIT_STATE_REQUIRED")
    return expected


def _state_vector(raw: Any, expected_names: Sequence[str]) -> tuple[float, ...]:
    names = tuple(expected_names)
    if not names:
        if raw in (None, "", {}):
            return ()
        raise ValueError("NFL_M2_V2E_UNEXPECTED_STATE_VECTOR")
    if not isinstance(raw, Mapping):
        raise ValueError("NFL_M2_V2E_STATE_VECTOR_INVALID")
    for key in raw:
        if str(key).strip().lower() in _PROHIBITED_MARKET_KEYS:
            raise ValueError(f"NFL_M2_V2E_MARKET_DATA_PROHIBITED:{key}")
    raw_names = tuple(sorted(str(key) for key in raw))
    if raw_names != names:
        raise ValueError("NFL_M2_V2E_STATE_SCHEMA_MISMATCH")
    return tuple(
        _finite_float(raw[name], reason="NFL_M2_V2E_STATE_VECTOR_INVALID")
        for name in names
    )


def _outcome_counts(row: Mapping[str, Any], side: str) -> tuple[int, ...]:
    prefix = f"{side}_"
    counts = tuple(
        _nonnegative_int(row.get(prefix + outcome, 0), reason="NFL_M2_V2E_OUTCOME_COUNT_INVALID")
        for outcome in _OUTCOMES
    )
    drives = _nonnegative_int(row.get(prefix + "drives"), reason="NFL_M2_V2E_DRIVE_COUNT_INVALID")
    if sum(counts) != drives:
        raise ValueError(f"NFL_M2_V2E_DRIVE_OUTCOME_SUM_MISMATCH:{side}")
    return counts


def _poisson_pmf(k: int, mean: float) -> float:
    if k < 0 or mean <= 0.0:
        return 0.0
    return exp(-mean + k * log(mean) - lgamma(k + 1.0))


def _poisson_quantile(u: float, mean: float, *, maximum: int = 24) -> int:
    cumulative = 0.0
    for k in range(maximum + 1):
        cumulative += _poisson_pmf(k, mean)
        if u <= cumulative:
            return k
    return maximum


def _categorical_quantile(u: float, probabilities: tuple[float, ...]) -> int:
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if u <= cumulative or index == len(probabilities) - 1:
            return index
    raise AssertionError("unreachable")


def _stratified_unit(index: int, path_count: int, dimension: int) -> float:
    """Deterministic full-support stratified uniform variate."""
    if path_count <= 0 or index < 0 or index >= path_count or dimension < 0:
        raise ValueError("NFL_M2_V2E_STRATIFIED_UNIT_ARGUMENT_INVALID")
    multiplier = 2 * dimension + 1
    while gcd(multiplier, path_count) != 1:
        multiplier += 2
    offset = (dimension * 104729 + 12345) % path_count
    bucket = (index * multiplier + offset) % path_count
    return (bucket + 0.5) / float(path_count)


def _ridge(lhs: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


@dataclass(frozen=True)
class NFLM2V2ECandidateModel:
    model_id: str
    feature_contract: str
    distribution_contract: str
    train_seasons: tuple[int, ...]
    home_drive_mean: float
    away_drive_mean: float
    home_outcome_probabilities: tuple[float, ...]
    away_outcome_probabilities: tuple[float, ...]
    home_state_coefficients: tuple[float, ...]
    away_state_coefficients: tuple[float, ...]
    laplace_alpha: float
    state_feature_names: tuple[str, ...] = ()
    state_means: tuple[float, ...] = ()
    state_scales: tuple[float, ...] = ()
    home_outcome_state_coefficients: tuple[tuple[float, ...], ...] = ()
    away_outcome_state_coefficients: tuple[tuple[float, ...], ...] = ()
    state_ridge_alpha: float = NFL_M2_V2E_STATE_RIDGE_ALPHA
    promotion_eligible: bool = False


def _standardization(
    rows: list[dict[str, Any]],
    names: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    states = []
    for row in rows:
        states.append(_state_vector(row["home_state"], names))
        states.append(_state_vector(row["away_state"], names))
    matrix = np.asarray(states, dtype=float)
    means = matrix.mean(axis=0)
    scales = matrix.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    return means, scales


def _z(
    raw: Any,
    names: tuple[str, ...],
    means: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    vector = np.asarray(_state_vector(raw, names), dtype=float)
    return (vector - means) / scales


def _fit_drive_state(
    rows: list[dict[str, Any]],
    side: str,
    global_mean: float,
    names: tuple[str, ...],
    means: np.ndarray,
    scales: np.ndarray,
) -> tuple[float, ...]:
    x = np.asarray([_z(row[f"{side}_state"], names, means, scales) for row in rows], dtype=float)
    y = np.asarray([float(row[f"{side}_drives"]) - global_mean for row in rows], dtype=float)
    lhs = x.T @ x + np.eye(x.shape[1], dtype=float) * NFL_M2_V2E_STATE_RIDGE_ALPHA
    coef = _ridge(lhs, x.T @ y)
    return tuple(float(value) for value in coef.tolist())


def _fit_outcome_state(
    rows: list[dict[str, Any]],
    side: str,
    baseline: np.ndarray,
    names: tuple[str, ...],
    means: np.ndarray,
    scales: np.ndarray,
) -> tuple[tuple[float, ...], ...]:
    x = np.asarray([_z(row[f"{side}_state"], names, means, scales) for row in rows], dtype=float)
    drives = np.asarray([float(row[f"{side}_drives"]) for row in rows], dtype=float)
    if np.any(drives <= 0.0):
        raise ValueError("NFL_M2_V2E_DRIVE_COUNT_INVALID")
    shares = np.asarray(
        [
            np.asarray(_outcome_counts(row, side), dtype=float) / float(row[f"{side}_drives"])
            for row in rows
        ],
        dtype=float,
    )
    residual = shares - baseline.reshape(1, -1)
    weighted_x = x * drives[:, None]
    lhs = x.T @ weighted_x + np.eye(x.shape[1], dtype=float) * NFL_M2_V2E_STATE_RIDGE_ALPHA
    rhs = x.T @ (residual * drives[:, None])
    coef = _ridge(lhs, rhs)
    return tuple(tuple(float(value) for value in feature_row) for feature_row in coef.tolist())


def fit_nfl_m2_v2e_candidate(
    rows: Iterable[Mapping[str, Any]],
    *,
    laplace_alpha: float = 1.0,
) -> NFLM2V2ECandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2E_TRAINING_ROWS_INSUFFICIENT")
    alpha = _finite_float(laplace_alpha, reason="NFL_M2_V2E_LAPLACE_ALPHA_INVALID")
    if alpha <= 0.0:
        raise ValueError("NFL_M2_V2E_LAPLACE_ALPHA_INVALID")

    names = _state_names(data)
    means, scales = _standardization(data, names)

    seasons: set[int] = set()
    home_counts = np.zeros(len(_OUTCOMES), dtype=float)
    away_counts = np.zeros(len(_OUTCOMES), dtype=float)
    home_drives: list[int] = []
    away_drives: list[int] = []

    for row in data:
        _assert_market_blind(row)
        try:
            seasons.add(int(row["season"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("NFL_M2_V2E_SEASON_REQUIRED") from exc
        h_counts = _outcome_counts(row, "home")
        a_counts = _outcome_counts(row, "away")
        home_counts += np.asarray(h_counts, dtype=float)
        away_counts += np.asarray(a_counts, dtype=float)
        home_drives.append(int(row["home_drives"]))
        away_drives.append(int(row["away_drives"]))

    home_mean = float(np.mean(home_drives))
    away_mean = float(np.mean(away_drives))
    if home_mean <= 0.0 or away_mean <= 0.0:
        raise ValueError("NFL_M2_V2E_DRIVE_MEAN_INVALID")

    home_probs = (home_counts + alpha) / float(home_counts.sum() + alpha * len(_OUTCOMES))
    away_probs = (away_counts + alpha) / float(away_counts.sum() + alpha * len(_OUTCOMES))
    return NFLM2V2ECandidateModel(
        model_id=NFL_M2_V2E_CANDIDATE_MODEL_ID,
        feature_contract=NFL_M2_V2E_FEATURE_CONTRACT,
        distribution_contract=NFL_M2_V2E_DISTRIBUTION_CONTRACT,
        train_seasons=tuple(sorted(seasons)),
        home_drive_mean=home_mean,
        away_drive_mean=away_mean,
        home_outcome_probabilities=tuple(float(v) for v in home_probs.tolist()),
        away_outcome_probabilities=tuple(float(v) for v in away_probs.tolist()),
        home_state_coefficients=_fit_drive_state(data, "home", home_mean, names, means, scales),
        away_state_coefficients=_fit_drive_state(data, "away", away_mean, names, means, scales),
        laplace_alpha=alpha,
        state_feature_names=names,
        state_means=tuple(float(value) for value in means.tolist()),
        state_scales=tuple(float(value) for value in scales.tolist()),
        home_outcome_state_coefficients=_fit_outcome_state(
            data, "home", home_probs, names, means, scales
        ),
        away_outcome_state_coefficients=_fit_outcome_state(
            data, "away", away_probs, names, means, scales
        ),
        state_ridge_alpha=NFL_M2_V2E_STATE_RIDGE_ALPHA,
        promotion_eligible=False,
    )


def _standardized_prediction_state(model: NFLM2V2ECandidateModel, raw: Any) -> tuple[float, ...]:
    names = tuple(model.state_feature_names)
    if not names:
        if raw in (None, "", {}):
            return ()
        raise ValueError("NFL_M2_V2E_UNEXPECTED_STATE_VECTOR")
    if len(model.state_means) != len(names) or len(model.state_scales) != len(names):
        raise ValueError("NFL_M2_V2E_STATE_STANDARDIZATION_INVALID")
    means = np.asarray(model.state_means, dtype=float)
    scales = np.asarray(model.state_scales, dtype=float)
    if np.any(scales <= 0.0):
        raise ValueError("NFL_M2_V2E_STATE_STANDARDIZATION_INVALID")
    return tuple(float(value) for value in _z(raw, names, means, scales).tolist())


def _conditional_drive_mean(
    base: float,
    coefficients: tuple[float, ...],
    state: tuple[float, ...],
) -> float:
    if not coefficients:
        if state:
            raise ValueError("NFL_M2_V2E_UNEXPECTED_STATE_VECTOR")
        return base
    if len(coefficients) != len(state):
        raise ValueError("NFL_M2_V2E_STATE_WIDTH_MISMATCH")
    return max(4.0, min(20.0, base + float(np.dot(coefficients, state))))


def _conditional_outcome_probabilities(
    baseline: tuple[float, ...],
    coefficients: tuple[tuple[float, ...], ...],
    state: tuple[float, ...],
) -> tuple[float, ...]:
    base = np.asarray(baseline, dtype=float)
    if base.shape != (len(_OUTCOMES),):
        raise ValueError("NFL_M2_V2E_OUTCOME_PROBABILITY_SHAPE_INVALID")
    if not coefficients:
        adjusted = base
    else:
        matrix = np.asarray(coefficients, dtype=float)
        if matrix.shape != (len(state), len(_OUTCOMES)):
            raise ValueError("NFL_M2_V2E_OUTCOME_STATE_SHAPE_INVALID")
        adjusted = base + np.asarray(state, dtype=float) @ matrix
    adjusted = np.clip(adjusted, _EPS, None)
    adjusted = adjusted / adjusted.sum()
    return tuple(float(value) for value in adjusted.tolist())


def derive_nfl_m2_v2e_score_distribution(
    model: NFLM2V2ECandidateModel,
    row: Mapping[str, Any],
    *,
    path_count: int = 4096,
) -> tuple[dict[str, int], ...]:
    if model.model_id != NFL_M2_V2E_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2E_MODEL_IDENTITY_INVALID")
    if model.feature_contract != NFL_M2_V2E_FEATURE_CONTRACT:
        raise ValueError("NFL_M2_V2E_FEATURE_CONTRACT_INVALID")
    if model.distribution_contract != NFL_M2_V2E_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2E_DISTRIBUTION_CONTRACT_INVALID")
    if model.promotion_eligible is not False:
        raise ValueError("NFL_M2_V2E_PROMOTION_MUST_REMAIN_FALSE")
    if path_count < 256:
        raise ValueError("NFL_M2_V2E_PATH_COUNT_TOO_SMALL")

    payload = dict(row)
    _assert_market_blind(payload)
    home_state = _standardized_prediction_state(model, payload.get("home_state"))
    away_state = _standardized_prediction_state(model, payload.get("away_state"))
    home_mean = _conditional_drive_mean(model.home_drive_mean, model.home_state_coefficients, home_state)
    away_mean = _conditional_drive_mean(model.away_drive_mean, model.away_state_coefficients, away_state)
    home_outcome_probs = _conditional_outcome_probabilities(
        model.home_outcome_probabilities, model.home_outcome_state_coefficients, home_state
    )
    away_outcome_probs = _conditional_outcome_probabilities(
        model.away_outcome_probabilities, model.away_outcome_state_coefficients, away_state
    )

    paths: list[dict[str, int]] = []
    for index in range(path_count):
        home_drive_u = _stratified_unit(index, path_count, 1)
        away_drive_u = _stratified_unit(index, path_count, 2)
        home_drives = _poisson_quantile(home_drive_u, home_mean)
        away_drives = _poisson_quantile(away_drive_u, away_mean)

        home_score = 0
        away_score = 0
        for drive in range(home_drives):
            u = _stratified_unit(index, path_count, 100 + drive)
            outcome = _OUTCOMES[_categorical_quantile(u, home_outcome_probs)]
            home_score += _OWN_POINTS[outcome]
            if outcome == "safety_allowed":
                away_score += 2
            elif outcome == "def_td_7_allowed":
                away_score += 7

        for drive in range(away_drives):
            u = _stratified_unit(index, path_count, 1000 + drive)
            outcome = _OUTCOMES[_categorical_quantile(u, away_outcome_probs)]
            away_score += _OWN_POINTS[outcome]
            if outcome == "safety_allowed":
                home_score += 2
            elif outcome == "def_td_7_allowed":
                home_score += 7

        paths.append({"home_score": home_score, "away_score": away_score})
    return tuple(paths)
