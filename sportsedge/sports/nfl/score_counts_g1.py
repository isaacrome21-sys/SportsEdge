"""Research-only NFL scoring-count joint score model.

This module implements the frozen NFL_SCORE_COUNTS_G1 architecture without
reading sportsbook markets or granting bettor-facing authority. Historical or
forward scoring is handled by separate governed runners.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import exp, isfinite, log
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_CORE_V1"
ROOT_SEED_LITERAL = "SportsEdge|NFL_SCORE_COUNTS_G1|FORWARD_V1|ROOT_SEED"
ROOT_SEED_UINT64 = 16316594915016045197

FEATURE_NAMES = (
    "off_epa_per_play",
    "opp_def_epa_allowed_per_play",
    "off_success_rate",
    "opp_def_success_rate_allowed",
    "off_pass_epa_per_dropback",
    "opp_def_pass_epa_allowed_per_dropback",
    "off_rush_epa_per_rush",
    "opp_def_rush_epa_allowed_per_rush",
    "off_plays_per_game",
    "off_td_per_game",
    "opp_td_allowed_per_game",
    "made_fg_per_game",
    "opp_fg_allowed_per_game",
    "off_turnover_rate",
    "opp_takeaway_rate",
    "off_sack_rate_allowed",
    "opp_def_sack_rate",
    "starting_qb_epa_shrunk",
    "starting_qb_cpoe_shrunk",
    "home_indicator",
)

ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)
FG_ATTEMPT2_FEATURE_NAMES = (
    "made_fg_per_game",
    "opp_fg_allowed_per_game",
    "off_plays_per_game",
    "home_indicator",
)
FG_ATTEMPT2_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)
SIGMA_GRID = (0.0, 0.10, 0.20, 0.30)


class ScoreCountsError(ValueError):
    pass


@dataclass(frozen=True)
class PoissonRidge:
    target: str
    alpha: float
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]


@dataclass(frozen=True)
class ScoreCountFit:
    td_model: PoissonRidge
    fg_model: PoissonRidge
    shared_sigma: float
    def_st_td_rate: float
    safety_rate: float
    conversion_probabilities: tuple[float, float, float]
    source_manifest_sha256: str
    code_identity: str


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ScoreCountsError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoreCountsError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise ScoreCountsError(f"{field}:FINITE_REQUIRED")
    return out


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def child_seed(game_id: str, *, root_seed: int = ROOT_SEED_UINT64) -> int:
    gid = str(game_id or "").strip()
    if not gid:
        raise ScoreCountsError("GAME_ID_REQUIRED")
    digest = sha256(f"{root_seed}|{gid}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _validated_feature_names(feature_names: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(name) for name in feature_names)
    if not names or len(set(names)) != len(names):
        raise ScoreCountsError("FEATURE_IDENTITY_MISMATCH")
    if any(name not in FEATURE_NAMES for name in names):
        raise ScoreCountsError("FEATURE_IDENTITY_MISMATCH")
    return names


def _matrix(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> np.ndarray:
    if not rows:
        raise ScoreCountsError("TRAINING_ROWS_REQUIRED")
    names = _validated_feature_names(feature_names)
    out = []
    for idx, row in enumerate(rows):
        vals = [_finite(row.get(name), f"row[{idx}].{name}") for name in names]
        out.append(vals)
    return np.asarray(out, dtype=float)


def _target(rows: Sequence[Mapping[str, Any]], field: str) -> np.ndarray:
    vals = []
    for idx, row in enumerate(rows):
        value = _finite(row.get(field), f"row[{idx}].{field}")
        if value < 0 or abs(value - round(value)) > 1e-9:
            raise ScoreCountsError(f"row[{idx}].{field}:NONNEGATIVE_INTEGER_REQUIRED")
        vals.append(value)
    return np.asarray(vals, dtype=float)


def _standardize(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = np.mean(x, axis=0)
    scale = np.std(x, axis=0, ddof=0)
    scale = np.where(scale < 1e-9, 1.0, scale)
    return (x - mean) / scale, mean, scale


def _poisson_deviance(y: np.ndarray, mu: np.ndarray) -> float:
    if y.shape != mu.shape or y.size == 0:
        raise ScoreCountsError("POISSON_DEVIANCE_SHAPE")
    mu = np.clip(mu, 1e-12, None)
    term = np.where(y > 0, y * np.log(y / mu) - (y - mu), mu)
    return float(2.0 * np.mean(term))


def fit_poisson_ridge(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    alpha: float,
    feature_names: Sequence[str] = FEATURE_NAMES,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> PoissonRidge:
    if alpha < 0:
        raise ScoreCountsError("ALPHA_NONNEGATIVE_REQUIRED")
    names = _validated_feature_names(feature_names)
    x_raw = _matrix(rows, feature_names=names)
    y = _target(rows, target)
    x, mean, scale = _standardize(x_raw)
    design = np.column_stack([np.ones(x.shape[0]), x])
    beta = np.zeros(design.shape[1], dtype=float)
    beta[0] = log(max(float(np.mean(y)), 1e-6))
    penalty = np.zeros(design.shape[1], dtype=float)
    penalty[1:] = float(alpha)

    for _ in range(max_iter):
        eta = np.clip(design @ beta, -20.0, 20.0)
        mu = np.exp(eta)
        grad = design.T @ (mu - y) + penalty * beta
        hess = design.T @ (design * mu[:, None]) + np.diag(penalty)
        hess += np.eye(hess.shape[0]) * 1e-10
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError as exc:
            raise ScoreCountsError("POISSON_RIDGE_SINGULAR") from exc
        beta_next = beta - step
        if float(np.max(np.abs(beta_next - beta))) <= tol:
            beta = beta_next
            break
        beta = beta_next

    if not np.all(np.isfinite(beta)):
        raise ScoreCountsError("POISSON_RIDGE_NONFINITE")
    return PoissonRidge(
        target=target,
        alpha=float(alpha),
        feature_names=names,
        mean=tuple(float(v) for v in mean),
        scale=tuple(float(v) for v in scale),
        intercept=float(beta[0]),
        coefficients=tuple(float(v) for v in beta[1:]),
    )


def predict_mean(model: PoissonRidge, row: Mapping[str, Any]) -> float:
    names = _validated_feature_names(model.feature_names)
    x = np.asarray([_finite(row.get(name), name) for name in names], dtype=float)
    mean = np.asarray(model.mean, dtype=float)
    scale = np.asarray(model.scale, dtype=float)
    beta = np.asarray(model.coefficients, dtype=float)
    eta = float(model.intercept + ((x - mean) / scale) @ beta)
    return float(exp(max(-20.0, min(20.0, eta))))


def _season(row: Mapping[str, Any], idx: int) -> int:
    value = _finite(row.get("season"), f"row[{idx}].season")
    if abs(value - round(value)) > 1e-9:
        raise ScoreCountsError(f"row[{idx}].season:INTEGER_REQUIRED")
    return int(round(value))


def choose_alpha(
    rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    alphas: Sequence[float] = ALPHA_GRID,
    feature_names: Sequence[str] = FEATURE_NAMES,
) -> tuple[float, dict[float, float]]:
    seasons = sorted({_season(row, idx) for idx, row in enumerate(rows)})
    if len(seasons) < 3:
        raise ScoreCountsError("AT_LEAST_THREE_DEVELOPMENT_SEASONS_REQUIRED")
    scores: dict[float, list[float]] = {float(a): [] for a in alphas}
    for validation_season in seasons[1:]:
        train = [row for row in rows if int(row["season"]) < validation_season]
        valid = [row for row in rows if int(row["season"]) == validation_season]
        if not train or not valid:
            continue
        y = _target(valid, target)
        for alpha in scores:
            model = fit_poisson_ridge(
                train, target=target, alpha=alpha, feature_names=feature_names
            )
            mu = np.asarray([predict_mean(model, row) for row in valid], dtype=float)
            scores[alpha].append(_poisson_deviance(y, mu))
    means = {
        alpha: float(np.mean(values)) if values else float("inf")
        for alpha, values in scores.items()
    }
    best = min(means, key=lambda a: (means[a], a))
    if not isfinite(means[best]):
        raise ScoreCountsError("ALPHA_CV_NO_VALID_FOLDS")
    return float(best), means


def empirical_bayes_rate(
    *,
    events: float,
    exposure: float,
    league_rate: float,
    prior_exposure: float = 25.0,
) -> float:
    e = _finite(events, "events")
    n = _finite(exposure, "exposure")
    rate = _finite(league_rate, "league_rate")
    prior = _finite(prior_exposure, "prior_exposure")
    if e < 0 or n < 0 or prior <= 0 or not 0 <= rate <= 1:
        raise ScoreCountsError("EMPIRICAL_BAYES_INPUT_INVALID")
    return float((e + prior * rate) / (n + prior))


def fit_core(
    rows: Sequence[Mapping[str, Any]],
    *,
    shared_sigma: float,
    def_st_td_rate: float,
    safety_rate: float,
    conversion_probabilities: Sequence[float],
    source_manifest_sha256: str,
    code_identity: str,
    fg_feature_names: Sequence[str] = FEATURE_NAMES,
    fg_alphas: Sequence[float] = ALPHA_GRID,
) -> ScoreCountFit:
    if shared_sigma not in SIGMA_GRID:
        raise ScoreCountsError("SHARED_SIGMA_NOT_FROZEN_GRID")
    digest = str(source_manifest_sha256 or "")
    if len(digest) != 64:
        raise ScoreCountsError("SOURCE_MANIFEST_SHA256_REQUIRED")
    code = str(code_identity or "").strip()
    if not code:
        raise ScoreCountsError("CODE_IDENTITY_REQUIRED")
    probs = tuple(_finite(v, "conversion_probability") for v in conversion_probabilities)
    if len(probs) != 3 or any(v < 0 for v in probs) or abs(sum(probs) - 1.0) > 1e-9:
        raise ScoreCountsError("CONVERSION_PROBABILITIES_INVALID")
    dst = _finite(def_st_td_rate, "def_st_td_rate")
    safety = _finite(safety_rate, "safety_rate")
    if dst < 0 or safety < 0:
        raise ScoreCountsError("RARE_SCORE_RATE_NEGATIVE")

    td_alpha, _ = choose_alpha(rows, target="offense_touchdowns")
    fg_names = _validated_feature_names(fg_feature_names)
    fg_alpha, _ = choose_alpha(
        rows,
        target="made_field_goals",
        alphas=fg_alphas,
        feature_names=fg_names,
    )
    return ScoreCountFit(
        td_model=fit_poisson_ridge(rows, target="offense_touchdowns", alpha=td_alpha),
        fg_model=fit_poisson_ridge(
            rows,
            target="made_field_goals",
            alpha=fg_alpha,
            feature_names=fg_names,
        ),
        shared_sigma=float(shared_sigma),
        def_st_td_rate=dst,
        safety_rate=safety,
        conversion_probabilities=probs,
        source_manifest_sha256=digest,
        code_identity=code,
    )


def _team_rate_override(
    row: Mapping[str, Any],
    key: str,
    fallback: float,
) -> float:
    value = row.get(key)
    if value in (None, ""):
        return float(fallback)
    out = _finite(value, key)
    if out < 0:
        raise ScoreCountsError(f"{key}:NEGATIVE")
    return out


def _team_conversion_override(
    row: Mapping[str, Any],
    fallback: tuple[float, float, float],
) -> tuple[float, float, float]:
    keys = ("conversion_pat_p", "conversion_two_p", "conversion_no_p")
    supplied = [row.get(key) not in (None, "") for key in keys]
    if not any(supplied):
        return fallback
    if not all(supplied):
        raise ScoreCountsError("TEAM_CONVERSION_OVERRIDE_INCOMPLETE")
    probs = tuple(_finite(row.get(key), key) for key in keys)
    if any(v < 0 for v in probs) or abs(sum(probs) - 1.0) > 1e-9:
        raise ScoreCountsError("TEAM_CONVERSION_OVERRIDE_INVALID")
    return probs


def _conversions(
    rng: np.random.Generator,
    touchdowns: np.ndarray,
    probabilities: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    pat_p, two_p, no_p = probabilities
    conversion_mass = two_p + no_p
    pats = rng.binomial(touchdowns, pat_p)
    remaining = touchdowns - pats
    p_two_cond = 0.0 if conversion_mass <= 0 else two_p / conversion_mass
    twos = rng.binomial(remaining, p_two_cond)
    return pats.astype(int), twos.astype(int)


def simulate_game(
    fit: ScoreCountFit,
    *,
    game_id: str,
    home_row: Mapping[str, Any],
    away_row: Mapping[str, Any],
    paths: int = 50000,
    seed: int | None = None,
) -> dict[str, Any]:
    if paths < 1:
        raise ScoreCountsError("PATHS_POSITIVE_REQUIRED")
    if paths < 10000:
        status = "SMOKE_ONLY"
    else:
        status = "SCORED_PATH_COUNT"

    root = child_seed(game_id) if seed is None else int(seed)
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(root)))

    home_td_lambda = predict_mean(fit.td_model, home_row)
    away_td_lambda = predict_mean(fit.td_model, away_row)
    home_fg_lambda = predict_mean(fit.fg_model, home_row)
    away_fg_lambda = predict_mean(fit.fg_model, away_row)

    sigma = float(fit.shared_sigma)
    if sigma == 0.0:
        latent = np.ones(paths, dtype=float)
    else:
        latent = rng.lognormal(mean=-0.5 * sigma * sigma, sigma=sigma, size=paths)

    home_off_td = rng.poisson(home_td_lambda * latent)
    away_off_td = rng.poisson(away_td_lambda * latent)
    home_fg = rng.poisson(home_fg_lambda * latent)
    away_fg = rng.poisson(away_fg_lambda * latent)

    home_def_st_rate = _team_rate_override(home_row, "def_st_td_rate", fit.def_st_td_rate)
    away_def_st_rate = _team_rate_override(away_row, "def_st_td_rate", fit.def_st_td_rate)
    home_safety_rate = _team_rate_override(home_row, "safety_rate", fit.safety_rate)
    away_safety_rate = _team_rate_override(away_row, "safety_rate", fit.safety_rate)
    home_conversions = _team_conversion_override(home_row, fit.conversion_probabilities)
    away_conversions = _team_conversion_override(away_row, fit.conversion_probabilities)

    home_dst = rng.poisson(home_def_st_rate, size=paths)
    away_dst = rng.poisson(away_def_st_rate, size=paths)
    home_safety = rng.poisson(home_safety_rate, size=paths)
    away_safety = rng.poisson(away_safety_rate, size=paths)

    home_td = home_off_td + home_dst
    away_td = away_off_td + away_dst
    home_pat, home_two = _conversions(rng, home_td, home_conversions)
    away_pat, away_two = _conversions(rng, away_td, away_conversions)

    home_score = 6 * home_td + home_pat + 2 * home_two + 3 * home_fg + 2 * home_safety
    away_score = 6 * away_td + away_pat + 2 * away_two + 3 * away_fg + 2 * away_safety
    margin = home_score - away_score
    total = home_score + away_score

    return {
        "schema": SCHEMA,
        "status": status,
        "game_id": str(game_id),
        "seed": root,
        "paths": int(paths),
        "home_score": home_score,
        "away_score": away_score,
        "home_team_tds": home_td,
        "away_team_tds": away_td,
        "margin": margin,
        "total": total,
        "means": {
            "home_score": float(np.mean(home_score)),
            "away_score": float(np.mean(away_score)),
            "margin": float(np.mean(margin)),
            "total": float(np.mean(total)),
        },
        "model": {
            "home_off_td_lambda": home_td_lambda,
            "away_off_td_lambda": away_td_lambda,
            "home_fg_lambda": home_fg_lambda,
            "away_fg_lambda": away_fg_lambda,
            "shared_sigma": sigma,
            "home_def_st_td_rate": home_def_st_rate,
            "away_def_st_td_rate": away_def_st_rate,
            "home_safety_rate": home_safety_rate,
            "away_safety_rate": away_safety_rate,
            "home_conversion_probabilities": home_conversions,
            "away_conversion_probabilities": away_conversions,
        },
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


def market_probability(
    simulation: Mapping[str, Any],
    *,
    market: str,
    selection: str,
    line: float | None = None,
) -> dict[str, float]:
    m = str(market or "").strip().lower()
    s = str(selection or "").strip().lower()
    home = np.asarray(simulation["home_score"])
    away = np.asarray(simulation["away_score"])
    margin = np.asarray(simulation["margin"])
    total = np.asarray(simulation["total"])

    if m == "moneyline":
        if s == "home":
            wins, pushes = home > away, home == away
        elif s == "away":
            wins, pushes = away > home, home == away
        else:
            raise ScoreCountsError("MONEYLINE_SELECTION_INVALID")
    elif m == "spread":
        if line is None:
            raise ScoreCountsError("SPREAD_LINE_REQUIRED")
        threshold = _finite(line, "line")
        if s == "home":
            value = margin + threshold
        elif s == "away":
            value = -margin + threshold
        else:
            raise ScoreCountsError("SPREAD_SELECTION_INVALID")
        wins, pushes = value > 0, value == 0
    elif m == "total":
        if line is None:
            raise ScoreCountsError("TOTAL_LINE_REQUIRED")
        threshold = _finite(line, "line")
        if s == "over":
            wins, pushes = total > threshold, total == threshold
        elif s == "under":
            wins, pushes = total < threshold, total == threshold
        else:
            raise ScoreCountsError("TOTAL_SELECTION_INVALID")
    elif m == "team_total":
        if line is None:
            raise ScoreCountsError("TEAM_TOTAL_LINE_REQUIRED")
        threshold = _finite(line, "line")
        if s == "home_over":
            wins, pushes = home > threshold, home == threshold
        elif s == "home_under":
            wins, pushes = home < threshold, home == threshold
        elif s == "away_over":
            wins, pushes = away > threshold, away == threshold
        elif s == "away_under":
            wins, pushes = away < threshold, away == threshold
        else:
            raise ScoreCountsError("TEAM_TOTAL_SELECTION_INVALID")
    else:
        raise ScoreCountsError("MARKET_UNSUPPORTED")

    p_win = float(np.mean(wins))
    p_push = float(np.mean(pushes))
    return {
        "win_p": p_win,
        "push_p": p_push,
        "loss_p": float(1.0 - p_win - p_push),
    }


__all__ = [
    "ALPHA_GRID",
    "FEATURE_NAMES",
    "FG_ATTEMPT2_ALPHA_GRID",
    "FG_ATTEMPT2_FEATURE_NAMES",
    "ROOT_SEED_LITERAL",
    "ROOT_SEED_UINT64",
    "SCHEMA",
    "SIGMA_GRID",
    "PoissonRidge",
    "ScoreCountFit",
    "ScoreCountsError",
    "child_seed",
    "choose_alpha",
    "empirical_bayes_rate",
    "fit_core",
    "fit_poisson_ridge",
    "market_probability",
    "predict_mean",
    "simulate_game",
]
