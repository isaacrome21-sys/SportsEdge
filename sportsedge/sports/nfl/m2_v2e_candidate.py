"""NFL M2 V2E diagnostic candidate: possession-level discrete scoring model.

This module is research-only.  It deliberately leaves production M2, the
promotion registry, eligibility, staking, and market pricing untouched.

V2E changes the generative architecture rather than tuning the already-observed
V2A/V2B/V2C/V2D score-regression family.  Training rows contain only realized
football possession counts/outcomes plus pregame market-blind state.  The model
fits a small possession-count distribution and discrete scoring-event rates,
then creates coherent integer home/away scores before any sportsbook line is
applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, lgamma, log
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

NFL_M2_V2E_CANDIDATE_MODEL_ID = "nfl_m2_possession_discrete_v2e_candidate"
NFL_M2_V2E_DISTRIBUTION_CONTRACT = "NFL_M2_V2E_POSSESSION_DISCRETE_SCORE_V1"
NFL_M2_V2E_FEATURE_CONTRACT = "NFL_M2_V2E_MARKET_BLIND_DRIVE_STATE_V1"

_OUTCOMES = ("td_xp", "td_2pt", "td_no_try", "fg", "safety", "no_score")
_POINTS = {
    "td_xp": 7,
    "td_2pt": 8,
    "td_no_try": 6,
    "fg": 3,
    "safety": 2,
    "no_score": 0,
}
_PROHIBITED_MARKET_KEYS = {
    "spread", "spread_line", "total", "total_line", "moneyline", "odds",
    "price", "implied_probability", "closing_spread", "closing_total",
    "tickets", "handle", "consensus",
}


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


def _state_vector(raw: Any) -> tuple[float, ...]:
    if raw in (None, ""):
        return ()
    if isinstance(raw, Mapping):
        for key in raw:
            if str(key).strip().lower() in _PROHIBITED_MARKET_KEYS:
                raise ValueError(f"NFL_M2_V2E_MARKET_DATA_PROHIBITED:{key}")
        values = [raw[key] for key in sorted(raw)]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = list(raw)
    else:
        raise ValueError("NFL_M2_V2E_STATE_VECTOR_INVALID")
    return tuple(_finite_float(value, reason="NFL_M2_V2E_STATE_VECTOR_INVALID") for value in values)


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
    promotion_eligible: bool = False


def _fit_drive_state(
    rows: list[dict[str, Any]],
    side: str,
    global_mean: float,
) -> tuple[float, ...]:
    vectors = [_state_vector(row.get(f"{side}_state")) for row in rows]
    widths = {len(vector) for vector in vectors}
    if widths == {0}:
        return ()
    if len(widths) != 1 or 0 in widths:
        raise ValueError("NFL_M2_V2E_STATE_WIDTH_MISMATCH")
    x = np.asarray(vectors, dtype=float)
    y = np.asarray([float(row[f"{side}_drives"]) - global_mean for row in rows], dtype=float)
    # Fixed, non-searched ridge regularization. The intercept is omitted because
    # global_mean already owns the baseline drive rate.
    gram = x.T @ x + np.eye(x.shape[1], dtype=float) * 10.0
    coef = np.linalg.solve(gram, x.T @ y)
    return tuple(float(value) for value in coef.tolist())


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
        home_state_coefficients=_fit_drive_state(data, "home", home_mean),
        away_state_coefficients=_fit_drive_state(data, "away", away_mean),
        laplace_alpha=alpha,
        promotion_eligible=False,
    )


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
    # Keep the research diagnostic inside a physically plausible range without
    # introducing a fitted/tuned clipping parameter.
    return max(4.0, min(20.0, base + float(np.dot(coefficients, state))))


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
    home_state = _state_vector(payload.get("home_state"))
    away_state = _state_vector(payload.get("away_state"))
    home_mean = _conditional_drive_mean(model.home_drive_mean, model.home_state_coefficients, home_state)
    away_mean = _conditional_drive_mean(model.away_drive_mean, model.away_state_coefficients, away_state)

    # Deterministic low-discrepancy-style lattice. Different irrational-ish
    # multipliers decorrelate drive-count and scoring-event dimensions while
    # remaining byte-for-byte reproducible without an RNG dependency.
    paths: list[dict[str, int]] = []
    for index in range(path_count):
        base_u = (index + 0.5) / path_count
        home_drive_u = (base_u * 0.7548776662466927) % 1.0
        away_drive_u = (base_u * 0.5698402909980532 + 0.31) % 1.0
        home_drives = _poisson_quantile(home_drive_u, home_mean)
        away_drives = _poisson_quantile(away_drive_u, away_mean)

        home_score = 0
        for drive in range(home_drives):
            u = ((base_u + (drive + 1) * 0.4142135623730951) * 0.6180339887498949) % 1.0
            outcome = _OUTCOMES[_categorical_quantile(u, model.home_outcome_probabilities)]
            home_score += _POINTS[outcome]

        away_score = 0
        for drive in range(away_drives):
            u = ((base_u + (drive + 1) * 0.7320508075688772 + 0.17) * 0.4142135623730950) % 1.0
            outcome = _OUTCOMES[_categorical_quantile(u, model.away_outcome_probabilities)]
            away_score += _POINTS[outcome]

        paths.append({"home_score": home_score, "away_score": away_score})
    return tuple(paths)
