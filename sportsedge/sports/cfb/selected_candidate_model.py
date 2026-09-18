"""Production-serving model for a frozen CFB candidate family.

This module exists so whichever preregistered candidate wins can be served with the
same feature transform used during evaluation. It does not evaluate candidates,
consume an attempt, create Model_P, or grant promotion/betting authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

import numpy as np

from .candidate_model_v2 import candidate_feature_names, candidate_feature_vector
from .joint_model import _num, _ridge

CFB_SELECTED_CANDIDATE_MODEL_ID = "cfb_selected_candidate_ridge_residual_v1"
CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT = "CFB_SELECTED_CANDIDATE_FEATURES_V1"
CFB_SELECTED_CANDIDATE_SEED_POLICY = "EXPLICIT_NUMPY_PCG64_V1"


class CFBSelectedCandidateModelError(ValueError):
    pass


@dataclass(frozen=True)
class CFBSelectedCandidateScoreModel:
    model_id: str
    feature_contract: str
    family: str
    feature_names: tuple[str, ...]
    feature_means: tuple[float, ...]
    feature_scales: tuple[float, ...]
    home_coefficients: tuple[float, ...]
    away_coefficients: tuple[float, ...]
    residual_pairs: tuple[tuple[float, float], ...]
    overtime_deltas: tuple[tuple[int, int], ...]
    train_seasons: tuple[int, ...]
    ridge_alpha: float

    def predict_means(self, row: Mapping[str, Any]) -> tuple[float, float]:
        expected_names = candidate_feature_names(self.family)
        if tuple(self.feature_names) != expected_names:
            raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_FEATURE_NAMES_MISMATCH")
        raw = candidate_feature_vector(self.family, row)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        if raw.shape != means.shape or means.shape != scales.shape:
            raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_FEATURE_DIMENSION_MISMATCH")
        design = np.concatenate(([1.0], (raw - means) / scales))
        home = float(design @ np.asarray(self.home_coefficients, dtype=float))
        away = float(design @ np.asarray(self.away_coefficients, dtype=float))
        if not isfinite(home) or not isfinite(away):
            raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_PREDICTION_NONFINITE")
        return home, away

    def artifact_sha256(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def fit_cfb_selected_candidate_score_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    family: str,
    ridge_alpha: float,
) -> CFBSelectedCandidateScoreModel:
    """Fit one already-selected frozen family on caller-supplied training rows."""
    data = [dict(row) for row in rows]
    if len(data) < 20:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_TRAINING_ROWS_INSUFFICIENT")
    alpha = _num(ridge_alpha, "ridge_alpha")
    if alpha < 0:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_RIDGE_ALPHA_NEGATIVE")

    names = candidate_feature_names(family)
    raw = np.asarray([candidate_feature_vector(family, row) for row in data], dtype=float)
    if raw.ndim != 2 or raw.shape[1] != len(names):
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_FEATURE_DIMENSION_MISMATCH")
    means, scales = raw.mean(axis=0), raw.std(axis=0)
    scales = np.where(scales > 1e-12, scales, 1.0)
    design = np.column_stack((np.ones(len(data), dtype=float), (raw - means) / scales))
    home_y = np.asarray([_num(row.get("home_score"), "home_score") for row in data], dtype=float)
    away_y = np.asarray([_num(row.get("away_score"), "away_score") for row in data], dtype=float)
    if np.any(home_y < 0) or np.any(away_y < 0):
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_NEGATIVE_REALIZED_SCORE")

    home_coef = _ridge(design, home_y, alpha)
    away_coef = _ridge(design, away_y, alpha)
    home_resid = home_y - design @ home_coef
    away_resid = away_y - design @ away_coef
    residual_pairs = tuple((float(h), float(a)) for h, a in zip(home_resid.tolist(), away_resid.tolist()))

    overtime: list[tuple[int, int]] = []
    for row in data:
        if all(key in row for key in ("regulation_home_score", "regulation_away_score")):
            rh = int(_num(row.get("regulation_home_score"), "regulation_home_score"))
            ra = int(_num(row.get("regulation_away_score"), "regulation_away_score"))
            fh = int(_num(row.get("home_score"), "home_score"))
            fa = int(_num(row.get("away_score"), "away_score"))
            if rh == ra and fh != fa:
                dh, da = fh - rh, fa - ra
                if dh < 0 or da < 0 or dh == da:
                    raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_OVERTIME_DELTA_INVALID")
                overtime.append((dh, da))

    try:
        seasons = tuple(sorted({int(row["season"]) for row in data}))
    except (KeyError, TypeError, ValueError) as exc:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_SEASON_INVALID") from exc
    if not seasons:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_TRAIN_SEASONS_MISSING")

    return CFBSelectedCandidateScoreModel(
        model_id=CFB_SELECTED_CANDIDATE_MODEL_ID,
        feature_contract=CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT,
        family=family,
        feature_names=names,
        feature_means=tuple(map(float, means)),
        feature_scales=tuple(map(float, scales)),
        home_coefficients=tuple(map(float, home_coef)),
        away_coefficients=tuple(map(float, away_coef)),
        residual_pairs=residual_pairs,
        overtime_deltas=tuple(overtime),
        train_seasons=seasons,
        ridge_alpha=float(alpha),
    )


def simulate_cfb_selected_candidate_distribution(
    model: CFBSelectedCandidateScoreModel,
    row: Mapping[str, Any],
    *,
    seed: int,
    n_paths: int = 20000,
) -> tuple[dict[str, int], ...]:
    if model.model_id != CFB_SELECTED_CANDIDATE_MODEL_ID or model.feature_contract != CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_MODEL_IDENTITY_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_EXPLICIT_INTEGER_SEED_REQUIRED")
    if isinstance(n_paths, bool) or not isinstance(n_paths, int) or n_paths <= 0:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_N_PATHS_INVALID")
    if not model.residual_pairs:
        raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_RESIDUAL_DISTRIBUTION_MISSING")

    home_mu, away_mu = model.predict_means(row)
    rng = np.random.default_rng(int(seed))
    idx = rng.integers(0, len(model.residual_pairs), size=n_paths)
    out: list[dict[str, int]] = []
    for i in idx.tolist():
        hr, ar = model.residual_pairs[i]
        home = max(0, int(round(home_mu + hr)))
        away = max(0, int(round(away_mu + ar)))
        if home == away:
            if not model.overtime_deltas:
                raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_OVERTIME_PROFILE_REQUIRED_FOR_TIED_PATH")
            dh, da = model.overtime_deltas[int(rng.integers(0, len(model.overtime_deltas)))]
            home += int(dh)
            away += int(da)
            if home == away:
                raise CFBSelectedCandidateModelError("CFB_SELECTED_CANDIDATE_OVERTIME_PROFILE_DID_NOT_RESOLVE_TIE")
        out.append({"home_score": home, "away_score": away, "margin": home - away, "total": home + away})
    return tuple(out)


__all__ = [
    "CFB_SELECTED_CANDIDATE_FEATURE_CONTRACT",
    "CFB_SELECTED_CANDIDATE_MODEL_ID",
    "CFB_SELECTED_CANDIDATE_SEED_POLICY",
    "CFBSelectedCandidateModelError",
    "CFBSelectedCandidateScoreModel",
    "fit_cfb_selected_candidate_score_model",
    "simulate_cfb_selected_candidate_distribution",
]
