"""SportsEdge CFB enriched joint-score candidate (v2).

This is a CANDIDATE, not a promoted replacement for the existing CFB model. It adds the
audit-required opponent-adjusted / early-season / situational feature contract while
keeping Model_P market-blind. Final score coefficients are fit on all seasons strictly
before the outer test season; the simulation residual distribution is built from inner
chronological out-of-fold predictions rather than in-sample residuals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from sportsedge.core.leakage import assert_no_market_fields


CFB_JOINT_MODEL_V2_ID = "cfb_joint_ridge_oof_residual_v2"
CFB_FEATURE_CONTRACT_V2 = "CFB_JOINT_GAME_FEATURES_V2"
CFB_V2_SEED_POLICY = "EXPLICIT_NUMPY_PCG64_V1"

# Required team-state features. Values must already be point-in-time and opponent-
# adjusted by their own training-only feature pipeline where the name says adj_.
TEAM_FEATURES_V2 = (
    "adj_ppa_offense",
    "adj_ppa_defense",
    "adj_success_rate_offense",
    "adj_success_rate_defense",
    "adj_explosive_rate_offense",
    "adj_explosive_rate_defense",
    "adj_havoc_offense_allowed",
    "adj_havoc_defense_created",
    "adj_finishing_drives_offense",
    "adj_finishing_drives_defense",
    "adj_line_yards_offense",
    "adj_line_yards_defense",
    "prior_season_rating",
    "returning_production",
    "talent_composite",
    "portal_impact",
    "qb_continuity",
    "ol_continuity",
    "skill_continuity",
    "defensive_continuity",
    "coaching_continuity",
    "special_teams_prior",
    "pace",
)

GAME_FEATURES_V2 = (
    "hfa_points",
    "rest_diff_days",
    "travel_diff_miles",
    "timezone_crossing_diff",
    "altitude_diff_feet",
    "wind_speed",
    "temperature",
    "indoors",
)


class CFBModelV2Error(ValueError):
    pass


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBModelV2Error(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBModelV2Error(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBModelV2Error(f"{field}:FINITE_REQUIRED")
    return out


def _team_features(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    value = row.get(f"{side}_features")
    if not isinstance(value, Mapping):
        raise CFBModelV2Error(f"{side.upper()}_FEATURES_REQUIRED")
    assert_no_market_fields(value)
    return value


def cfb_v2_feature_names() -> tuple[str, ...]:
    names = [f"home_{name}" for name in TEAM_FEATURES_V2]
    names += [f"away_{name}" for name in TEAM_FEATURES_V2]
    # Matchup differences are explicit rather than expecting the ridge to discover every
    # cross-side subtraction from separate coefficients in small early-season samples.
    names += [f"diff_{name}" for name in TEAM_FEATURES_V2]
    names += list(GAME_FEATURES_V2)
    return tuple(names)


def cfb_v2_feature_vector(row: Mapping[str, Any]) -> np.ndarray:
    # Final scores/settlement labels are outcomes; season/game identity is metadata. Every
    # other field is scanned for market leakage before being used by the predictive path.
    assert_no_market_fields({
        key: value
        for key, value in row.items()
        if key not in {
            "home_score", "away_score", "regulation_home_score", "regulation_away_score",
            "season", "week", "game_id", "game_start_ts", "feature_asof_ts",
        }
    })
    home = _team_features(row, "home")
    away = _team_features(row, "away")
    h = [_num(home.get(name), f"home.{name}") for name in TEAM_FEATURES_V2]
    a = [_num(away.get(name), f"away.{name}") for name in TEAM_FEATURES_V2]
    diffs = [x - y for x, y in zip(h, a)]
    context = row.get("game_features")
    if not isinstance(context, Mapping):
        raise CFBModelV2Error("GAME_FEATURES_REQUIRED")
    assert_no_market_fields(context)
    g = [_num(context.get(name), f"game.{name}") for name in GAME_FEATURES_V2]
    if context.get("indoors") not in {0, 0.0, 1, 1.0}:
        raise CFBModelV2Error("GAME_INDOORS_BINARY_REQUIRED")
    return np.asarray([*h, *a, *diffs, *g], dtype=float)


def _ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1], dtype=float) * float(alpha)
    penalty[0, 0] = 0.0
    lhs = design.T @ design + penalty
    rhs = design.T @ target
    try:
        return np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(lhs) @ rhs


def _fit_coefficients(rows: Sequence[Mapping[str, Any]], alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray([cfb_v2_feature_vector(row) for row in rows], dtype=float)
    means = raw.mean(axis=0)
    scales = raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(rows), dtype=float), (raw - means) / scales))
    home_y = np.asarray([_num(row.get("home_score"), "home_score") for row in rows], dtype=float)
    away_y = np.asarray([_num(row.get("away_score"), "away_score") for row in rows], dtype=float)
    if np.any(home_y < 0) or np.any(away_y < 0):
        raise CFBModelV2Error("NEGATIVE_REALIZED_SCORE")
    return means, scales, _ridge(design, home_y, alpha), _ridge(design, away_y, alpha)


def _predict_with(
    row: Mapping[str, Any],
    *,
    means: np.ndarray,
    scales: np.ndarray,
    home_coef: np.ndarray,
    away_coef: np.ndarray,
) -> tuple[float, float]:
    raw = cfb_v2_feature_vector(row)
    design = np.concatenate(([1.0], (raw - means) / scales))
    return float(design @ home_coef), float(design @ away_coef)


@dataclass(frozen=True)
class CFBJointScoreModelV2:
    model_id: str
    feature_contract: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    home_coefficients: tuple[float, ...]
    away_coefficients: tuple[float, ...]
    residual_pairs: tuple[tuple[float, float], ...]
    residual_oof_seasons: tuple[int, ...]
    overtime_deltas: tuple[tuple[int, int], ...]
    train_seasons: tuple[int, ...]
    outer_test_season: int
    ridge_alpha: float
    minimum_inner_train_seasons: int

    def validate(self) -> "CFBJointScoreModelV2":
        if self.model_id != CFB_JOINT_MODEL_V2_ID or self.feature_contract != CFB_FEATURE_CONTRACT_V2:
            raise CFBModelV2Error("MODEL_IDENTITY_INVALID")
        if self.outer_test_season in self.train_seasons or any(season >= self.outer_test_season for season in self.train_seasons):
            raise CFBModelV2Error("OUTER_TEST_SEASON_LEAK")
        if not self.residual_pairs or not self.residual_oof_seasons:
            raise CFBModelV2Error("OOF_RESIDUAL_DISTRIBUTION_REQUIRED")
        if not set(self.residual_oof_seasons).issubset(set(self.train_seasons)):
            raise CFBModelV2Error("OOF_RESIDUAL_SEASON_INVALID")
        return self

    def predict_means(self, row: Mapping[str, Any]) -> tuple[float, float]:
        self.validate()
        raw = cfb_v2_feature_vector(row)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape:
            raise CFBModelV2Error("MODEL_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        home = float(design @ np.asarray(self.home_coefficients, dtype=float))
        away = float(design @ np.asarray(self.away_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise CFBModelV2Error("MODEL_PREDICTION_NONFINITE")
        return home, away

    def artifact_sha256(self) -> str:
        self.validate()
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def fit_cfb_joint_score_model_v2_for_fold(
    rows: Iterable[Mapping[str, Any]],
    *,
    outer_test_season: int,
    ridge_alpha: float = 20.0,
    minimum_inner_train_seasons: int = 2,
    minimum_oof_residual_pairs: int = 20,
) -> CFBJointScoreModelV2:
    """Fit the enriched candidate without using the outer test season anywhere.

    Residual pairs come only from inner chronological holdout seasons. This avoids the
    under-dispersed simulation distribution created by bootstrapping residuals from the
    same observations used to fit final score coefficients.
    """

    data = [dict(row) for row in rows]
    if len(data) < 40:
        raise CFBModelV2Error("TRAINING_ROWS_INSUFFICIENT")
    test = int(outer_test_season)
    if any(int(row["season"]) >= test for row in data):
        raise CFBModelV2Error("OUTER_TEST_OR_FUTURE_SEASON_IN_TRAINING")
    alpha = _num(ridge_alpha, "ridge_alpha")
    if alpha < 0.0:
        raise CFBModelV2Error("RIDGE_ALPHA_NEGATIVE")
    minimum_inner = int(minimum_inner_train_seasons)
    if minimum_inner < 1:
        raise CFBModelV2Error("MINIMUM_INNER_TRAIN_SEASONS_INVALID")
    seasons = tuple(sorted({int(row["season"]) for row in data}))
    if len(seasons) <= minimum_inner:
        raise CFBModelV2Error("TRAINING_SEASONS_INSUFFICIENT_FOR_OOF_RESIDUALS")

    residual_pairs: list[tuple[float, float]] = []
    residual_seasons: list[int] = []
    for validation_season in seasons[minimum_inner:]:
        inner_train = [row for row in data if int(row["season"]) < validation_season]
        inner_valid = [row for row in data if int(row["season"]) == validation_season]
        if not inner_train or not inner_valid:
            continue
        means, scales, home_coef, away_coef = _fit_coefficients(inner_train, alpha)
        for row in inner_valid:
            home_mu, away_mu = _predict_with(
                row,
                means=means,
                scales=scales,
                home_coef=home_coef,
                away_coef=away_coef,
            )
            residual_pairs.append((
                _num(row.get("home_score"), "home_score") - home_mu,
                _num(row.get("away_score"), "away_score") - away_mu,
            ))
            residual_seasons.append(validation_season)
    if len(residual_pairs) < int(minimum_oof_residual_pairs):
        raise CFBModelV2Error("OOF_RESIDUAL_SAMPLE_INSUFFICIENT")

    means, scales, home_coef, away_coef = _fit_coefficients(data, alpha)
    overtime: list[tuple[int, int]] = []
    for row in data:
        if "regulation_home_score" not in row or "regulation_away_score" not in row:
            continue
        rh = int(_num(row["regulation_home_score"], "regulation_home_score"))
        ra = int(_num(row["regulation_away_score"], "regulation_away_score"))
        fh = int(_num(row["home_score"], "home_score"))
        fa = int(_num(row["away_score"], "away_score"))
        if rh == ra and fh != fa:
            dh, da = fh - rh, fa - ra
            if dh < 0 or da < 0 or dh == da:
                raise CFBModelV2Error("OVERTIME_DELTA_INVALID")
            overtime.append((dh, da))

    return CFBJointScoreModelV2(
        model_id=CFB_JOINT_MODEL_V2_ID,
        feature_contract=CFB_FEATURE_CONTRACT_V2,
        feature_names=cfb_v2_feature_names(),
        feature_means=tuple(map(float, means)),
        feature_scales=tuple(map(float, scales)),
        home_coefficients=tuple(map(float, home_coef)),
        away_coefficients=tuple(map(float, away_coef)),
        residual_pairs=tuple((float(h), float(a)) for h, a in residual_pairs),
        residual_oof_seasons=tuple(sorted(set(residual_seasons))),
        overtime_deltas=tuple(overtime),
        train_seasons=seasons,
        outer_test_season=test,
        ridge_alpha=alpha,
        minimum_inner_train_seasons=minimum_inner,
    ).validate()


def simulate_cfb_joint_distribution_v2(
    model: CFBJointScoreModelV2,
    row: Mapping[str, Any],
    *,
    seed: int,
    n_paths: int = 10000,
) -> tuple[dict[str, int], ...]:
    model.validate()
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise CFBModelV2Error("EXPLICIT_INTEGER_SEED_REQUIRED")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBModelV2Error("N_PATHS_INVALID")
    home_mu, away_mu = model.predict_means(row)
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(model.residual_pairs), size=n_paths)
    out: list[dict[str, int]] = []
    for index in idx.tolist():
        home_resid, away_resid = model.residual_pairs[index]
        home = max(0, int(round(home_mu + home_resid)))
        away = max(0, int(round(away_mu + away_resid)))
        if home == away:
            if not model.overtime_deltas:
                raise CFBModelV2Error("OVERTIME_PROFILE_REQUIRED_FOR_TIED_PATH")
            dh, da = model.overtime_deltas[int(rng.integers(0, len(model.overtime_deltas)))]
            home += int(dh)
            away += int(da)
            if home == away:
                raise CFBModelV2Error("OVERTIME_PROFILE_DID_NOT_RESOLVE_TIE")
        out.append({"home_score": home, "away_score": away, "margin": home - away, "total": home + away})
    return tuple(out)
