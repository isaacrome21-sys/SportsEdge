"""Leakage-resistant walk-forward validation for the CFB joint score model.

This module evaluates only realized scores from held-out seasons. Sportsbook prices are
not accepted here, so these diagnostics cannot by themselves establish CLV, ROI, EV,
or promotion eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping

from .joint_model import CFBModelError, fit_cfb_joint_score_model


class CFBOOSValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CFBOOSFold:
    holdout_season: int
    train_seasons: tuple[int, ...]
    n_train: int
    n_holdout: int
    home_rmse: float
    away_rmse: float
    margin_rmse: float
    total_rmse: float
    home_mae: float
    away_mae: float
    margin_mae: float
    total_mae: float


@dataclass(frozen=True)
class CFBOOSReport:
    schema_version: str
    status: str
    folds: tuple[CFBOOSFold, ...]
    n_predictions: int
    home_rmse: float
    away_rmse: float
    margin_rmse: float
    total_rmse: float
    home_mae: float
    away_mae: float
    margin_mae: float
    total_mae: float
    promotion_evidence: bool = False
    clv_evidence: bool = False
    roi_evidence: bool = False
    calibration_evidence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBOOSValidationError(f"CFB_OOS_NUMERIC_REQUIRED:{name}") from exc
    if not isfinite(out):
        raise CFBOOSValidationError(f"CFB_OOS_NONFINITE:{name}")
    return out


def _metrics(errors: list[float]) -> tuple[float, float]:
    if not errors:
        raise CFBOOSValidationError("CFB_OOS_EMPTY_ERRORS")
    return sqrt(sum(x * x for x in errors) / len(errors)), sum(abs(x) for x in errors) / len(errors)


def walk_forward_validate_cfb(
    rows: Iterable[Mapping[str, Any]], *, min_train_rows: int = 20, ridge_alpha: float = 10.0,
) -> CFBOOSReport:
    data = [dict(row) for row in rows]
    if not data:
        raise CFBOOSValidationError("CFB_OOS_ROWS_REQUIRED")
    for row in data:
        if "season" not in row:
            raise CFBOOSValidationError("CFB_OOS_SEASON_REQUIRED")
        _number(row.get("home_score"), "home_score")
        _number(row.get("away_score"), "away_score")
    seasons = sorted({int(row["season"]) for row in data})
    if len(seasons) < 2:
        raise CFBOOSValidationError("CFB_OOS_MULTIPLE_SEASONS_REQUIRED")

    folds: list[CFBOOSFold] = []
    all_home: list[float] = []
    all_away: list[float] = []
    all_margin: list[float] = []
    all_total: list[float] = []
    for holdout in seasons[1:]:
        train = [row for row in data if int(row["season"]) < holdout]
        test = [row for row in data if int(row["season"]) == holdout]
        if len(train) < int(min_train_rows) or not test:
            continue
        try:
            model = fit_cfb_joint_score_model(train, ridge_alpha=ridge_alpha)
        except CFBModelError as exc:
            raise CFBOOSValidationError(f"CFB_OOS_FIT_FAILED:{holdout}:{exc}") from exc
        he: list[float] = []; ae: list[float] = []; me: list[float] = []; te: list[float] = []
        for row in test:
            ph, pa = model.predict_means(row)
            ah = _number(row["home_score"], "home_score"); aa = _number(row["away_score"], "away_score")
            he.append(ph - ah); ae.append(pa - aa)
            me.append((ph - pa) - (ah - aa)); te.append((ph + pa) - (ah + aa))
        hr, hm = _metrics(he); ar, am = _metrics(ae); mr, mm = _metrics(me); tr, tm = _metrics(te)
        folds.append(CFBOOSFold(holdout, tuple(sorted({int(r["season"]) for r in train})), len(train), len(test), hr, ar, mr, tr, hm, am, mm, tm))
        all_home.extend(he); all_away.extend(ae); all_margin.extend(me); all_total.extend(te)
    if not folds:
        raise CFBOOSValidationError("CFB_OOS_NO_VALID_FOLDS")
    hr, hm = _metrics(all_home); ar, am = _metrics(all_away); mr, mm = _metrics(all_margin); tr, tm = _metrics(all_total)
    return CFBOOSReport("CFB_WALK_FORWARD_OOS_V1", "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE", tuple(folds), len(all_home), hr, ar, mr, tr, hm, am, mm, tm)
