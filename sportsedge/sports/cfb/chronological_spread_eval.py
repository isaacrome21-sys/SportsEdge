"""PIT-safe chronological evaluation for CFB spread candidate families.

This is research/evaluation plumbing only. It never consumes sportsbook lines as
features and grants no promotion, staking, or OFFICIAL authority.  The evaluator
measures predicted game margin (home score - away score) on strictly future
rows, which is the quantity the spread engine actually needs to improve.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .candidate_model_v2 import fit_cfb_candidate_score_model

CFB_CHRONOLOGICAL_SPREAD_EVAL_VERSION = "CFB_CHRONOLOGICAL_SPREAD_EVAL_V1"


class CFBChronologicalSpreadEvalError(ValueError):
    pass


def _instant(row: Mapping[str, Any]) -> datetime:
    raw = row.get("kickoff_utc")
    if not isinstance(raw, str) or not raw.strip():
        raise CFBChronologicalSpreadEvalError("CFB_KICKOFF_UTC_REQUIRED")
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBChronologicalSpreadEvalError("CFB_KICKOFF_UTC_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBChronologicalSpreadEvalError("CFB_KICKOFF_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class CFBSpreadFoldResult:
    cutoff_utc: str
    n_train: int
    n_test: int
    margin_rmse: float
    margin_mae: float
    margin_bias: float


@dataclass(frozen=True)
class CFBSpreadEvaluation:
    family: str
    folds: tuple[CFBSpreadFoldResult, ...]
    pooled_margin_rmse: float
    pooled_margin_mae: float
    pooled_margin_bias: float
    n_predictions: int


def evaluate_candidate_spread_chronologically(
    rows: Iterable[Mapping[str, Any]], *, family: str, ridge_alpha: float,
    cutoffs_utc: Sequence[str], min_train_rows: int = 20,
) -> CFBSpreadEvaluation:
    """Evaluate margin predictions using only observations before each cutoff.

    For every cutoff, training rows have kickoff < cutoff. Test rows run from the
    cutoff (inclusive) to the next cutoff (exclusive), or to the end for the last
    fold. A game can therefore never train a model that predicts itself or an
    earlier game. Caller-supplied team metrics must already be point-in-time safe.
    """
    data = [dict(r) for r in rows]
    if not data:
        raise CFBChronologicalSpreadEvalError("CFB_SPREAD_EVAL_ROWS_REQUIRED")
    stamped = sorted(((_instant(r), r) for r in data), key=lambda x: x[0])
    cutoffs = [_instant({"kickoff_utc": c}) for c in cutoffs_utc]
    if not cutoffs or cutoffs != sorted(set(cutoffs)):
        raise CFBChronologicalSpreadEvalError("CFB_SPREAD_EVAL_CUTOFFS_STRICTLY_INCREASING")
    if isinstance(min_train_rows, bool) or int(min_train_rows) < 20:
        raise CFBChronologicalSpreadEvalError("CFB_SPREAD_EVAL_MIN_TRAIN_INVALID")

    folds: list[CFBSpreadFoldResult] = []
    all_errors: list[float] = []
    for i, cutoff in enumerate(cutoffs):
        upper = cutoffs[i + 1] if i + 1 < len(cutoffs) else None
        train = [r for ts, r in stamped if ts < cutoff]
        test = [r for ts, r in stamped if ts >= cutoff and (upper is None or ts < upper)]
        if len(train) < int(min_train_rows) or not test:
            continue
        model = fit_cfb_candidate_score_model(train, family=family, ridge_alpha=ridge_alpha)
        errors: list[float] = []
        for row in test:
            home, away = model.predict_means(row)
            actual = float(row["home_score"]) - float(row["away_score"])
            errors.append((home - away) - actual)
        arr = np.asarray(errors, dtype=float)
        folds.append(CFBSpreadFoldResult(
            cutoff_utc=cutoff.isoformat().replace("+00:00", "Z"), n_train=len(train), n_test=len(test),
            margin_rmse=float(sqrt(float(np.mean(arr * arr)))),
            margin_mae=float(np.mean(np.abs(arr))), margin_bias=float(np.mean(arr)),
        ))
        all_errors.extend(errors)
    if not all_errors:
        raise CFBChronologicalSpreadEvalError("CFB_SPREAD_EVAL_NO_ADMISSIBLE_FOLDS")
    pooled = np.asarray(all_errors, dtype=float)
    return CFBSpreadEvaluation(
        family=family, folds=tuple(folds),
        pooled_margin_rmse=float(sqrt(float(np.mean(pooled * pooled)))),
        pooled_margin_mae=float(np.mean(np.abs(pooled))), pooled_margin_bias=float(np.mean(pooled)),
        n_predictions=len(all_errors),
    )


__all__ = [
    "CFB_CHRONOLOGICAL_SPREAD_EVAL_VERSION", "CFBChronologicalSpreadEvalError",
    "CFBSpreadFoldResult", "CFBSpreadEvaluation", "evaluate_candidate_spread_chronologically",
]
