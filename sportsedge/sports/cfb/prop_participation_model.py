"""Market-blind CFB participation/substitution model candidate.

This module closes one structural gap in the shared football prop simulator: CFB
starter exposure changes materially with game state and substitution.  The model
is deliberately separate from bettor-facing engine authority.  It can fit and
replay starter-retention probabilities from historical participation rows, but
it cannot promote a market or create production Model_P by itself.

Only realized football state is accepted as a feature: quarter, game clock,
score margin from the player's team perspective, and coarse position group.
Sportsbook lines, prices, implied probabilities, consensus, hit rates and capper
inputs are not accepted by the training contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import exp, isfinite
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

SCHEMA_VERSION = "CFB_PROP_PARTICIPATION_MODEL_V1"
FEATURE_NAMES = (
    "intercept",
    "third_quarter",
    "fourth_quarter",
    "late_game_fraction",
    "lead_14_plus",
    "trail_14_plus",
)
POSITION_GROUPS = frozenset({"QB", "RB", "WR", "TE", "OTHER"})
_ALLOWED_ROW_FIELDS = frozenset({
    "game_id",
    "season",
    "week",
    "event_ts",
    "position_group",
    "starter_on_play",
    "quarter",
    "clock_seconds_remaining",
    "score_margin",
    "source_sha256",
})


class CFBParticipationModelError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(raw).hexdigest()


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBParticipationModelError(code)
    return text


def _finite(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBParticipationModelError(code) from exc
    if not isfinite(out):
        raise CFBParticipationModelError(code)
    return out


def _position_group(value: Any) -> str:
    group = str(value or "").strip().upper()
    if group not in POSITION_GROUPS:
        raise CFBParticipationModelError(f"CFB_PARTICIPATION_POSITION_GROUP_INVALID:{group}")
    return group


def _features(*, quarter: int, clock_seconds_remaining: int, score_margin: float) -> np.ndarray:
    if isinstance(quarter, bool) or not isinstance(quarter, int) or quarter not in (1, 2, 3, 4):
        raise CFBParticipationModelError("CFB_PARTICIPATION_QUARTER_INVALID")
    if (
        isinstance(clock_seconds_remaining, bool)
        or not isinstance(clock_seconds_remaining, int)
        or not 0 <= clock_seconds_remaining <= 900
    ):
        raise CFBParticipationModelError("CFB_PARTICIPATION_CLOCK_INVALID")
    margin = _finite(score_margin, "CFB_PARTICIPATION_SCORE_MARGIN_INVALID")
    elapsed = (quarter - 1) * 900 + (900 - clock_seconds_remaining)
    late_fraction = elapsed / 3600.0
    return np.asarray(
        (
            1.0,
            1.0 if quarter == 3 else 0.0,
            1.0 if quarter == 4 else 0.0,
            late_fraction,
            max(0.0, margin - 13.0) / 14.0,
            max(0.0, -margin - 13.0) / 14.0,
        ),
        dtype=float,
    )


def _normalize_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBParticipationModelError("CFB_PARTICIPATION_ROW_INVALID")
    unknown = set(raw) - _ALLOWED_ROW_FIELDS
    if unknown:
        raise CFBParticipationModelError(
            "CFB_PARTICIPATION_ROW_FIELD_FORBIDDEN:" + ",".join(sorted(str(x) for x in unknown))
        )
    missing = _ALLOWED_ROW_FIELDS - set(raw)
    if missing:
        raise CFBParticipationModelError(
            "CFB_PARTICIPATION_ROW_FIELD_REQUIRED:" + ",".join(sorted(missing))
        )
    game_id = str(raw.get("game_id") or "").strip()
    event_ts = str(raw.get("event_ts") or "").strip()
    if not game_id or not event_ts:
        raise CFBParticipationModelError("CFB_PARTICIPATION_ROW_IDENTITY_REQUIRED")
    season = raw.get("season")
    week = raw.get("week")
    if isinstance(season, bool) or not isinstance(season, int) or season < 2000:
        raise CFBParticipationModelError("CFB_PARTICIPATION_SEASON_INVALID")
    if isinstance(week, bool) or not isinstance(week, int) or week < 0:
        raise CFBParticipationModelError("CFB_PARTICIPATION_WEEK_INVALID")
    starter = raw.get("starter_on_play")
    if type(starter) is not bool:
        raise CFBParticipationModelError("CFB_PARTICIPATION_OUTCOME_BOOL_REQUIRED")
    quarter = raw.get("quarter")
    clock = raw.get("clock_seconds_remaining")
    margin = _finite(raw.get("score_margin"), "CFB_PARTICIPATION_SCORE_MARGIN_INVALID")
    vector = _features(quarter=quarter, clock_seconds_remaining=clock, score_margin=margin)
    return {
        "game_id": game_id,
        "season": season,
        "week": week,
        "event_ts": event_ts,
        "position_group": _position_group(raw.get("position_group")),
        "starter_on_play": starter,
        "quarter": quarter,
        "clock_seconds_remaining": clock,
        "score_margin": margin,
        "source_sha256": _hex64(raw.get("source_sha256"), "CFB_PARTICIPATION_SOURCE_SHA256_INVALID"),
        "features": vector,
    }


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit_logistic_ridge(
    x: np.ndarray,
    y: np.ndarray,
    *,
    ridge_lambda: float,
    max_iter: int,
    tolerance: float,
) -> np.ndarray:
    if x.ndim != 2 or y.ndim != 1 or x.shape[0] != y.shape[0]:
        raise CFBParticipationModelError("CFB_PARTICIPATION_DESIGN_INVALID")
    if x.shape[0] < 2 or np.unique(y).size < 2:
        raise CFBParticipationModelError("CFB_PARTICIPATION_OUTCOME_VARIATION_REQUIRED")
    if ridge_lambda <= 0 or max_iter <= 0 or tolerance <= 0:
        raise CFBParticipationModelError("CFB_PARTICIPATION_FIT_PARAMETER_INVALID")
    beta = np.zeros(x.shape[1], dtype=float)
    penalty = np.eye(x.shape[1], dtype=float) * float(ridge_lambda)
    penalty[0, 0] = 0.0
    for _ in range(int(max_iter)):
        p = _sigmoid(x @ beta)
        w = np.maximum(p * (1.0 - p), 1e-8)
        hessian = x.T @ (w[:, None] * x) + penalty
        gradient = x.T @ (y - p) - penalty @ beta
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError as exc:
            raise CFBParticipationModelError("CFB_PARTICIPATION_FIT_SINGULAR") from exc
        beta = beta + step
        if float(np.max(np.abs(step))) <= float(tolerance):
            break
    if not np.all(np.isfinite(beta)):
        raise CFBParticipationModelError("CFB_PARTICIPATION_COEFFICIENT_NONFINITE")
    return beta


def fit_cfb_participation_model(
    rows: Iterable[Mapping[str, Any]],
    *,
    ridge_lambda: float = 1.0,
    min_rows_per_group: int = 30,
    max_iter: int = 100,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Fit deterministic per-position starter-retention hazards.

    The returned artifact is a candidate only.  `promotion_authority` is always
    false and the artifact explicitly requires walk-forward validation before it
    may be wired into bettor-facing CFB prop Model_P.
    """
    if isinstance(min_rows_per_group, bool) or not isinstance(min_rows_per_group, int) or min_rows_per_group < 2:
        raise CFBParticipationModelError("CFB_PARTICIPATION_MIN_ROWS_INVALID")
    normalized = [_normalize_row(row) for row in rows]
    if not normalized:
        raise CFBParticipationModelError("CFB_PARTICIPATION_ROWS_EMPTY")

    coefficients: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for group in sorted(POSITION_GROUPS):
        subset = [row for row in normalized if row["position_group"] == group]
        if not subset:
            continue
        if len(subset) < min_rows_per_group:
            raise CFBParticipationModelError(f"CFB_PARTICIPATION_GROUP_SAMPLE_TOO_SMALL:{group}:{len(subset)}")
        x = np.vstack([row["features"] for row in subset]).astype(float)
        y = np.asarray([1.0 if row["starter_on_play"] else 0.0 for row in subset], dtype=float)
        beta = _fit_logistic_ridge(
            x,
            y,
            ridge_lambda=float(ridge_lambda),
            max_iter=int(max_iter),
            tolerance=float(tolerance),
        )
        coefficients[group] = [float(value) for value in beta]
        counts[group] = len(subset)

    if "QB" not in coefficients:
        raise CFBParticipationModelError("CFB_PARTICIPATION_QB_GROUP_REQUIRED")

    source_rows = [
        {
            "game_id": row["game_id"],
            "season": row["season"],
            "week": row["week"],
            "event_ts": row["event_ts"],
            "position_group": row["position_group"],
            "source_sha256": row["source_sha256"],
        }
        for row in normalized
    ]
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "sport": "CFB",
        "model_role": "STARTER_RETENTION_AND_SUBSTITUTION_HAZARD_CANDIDATE",
        "feature_names": list(FEATURE_NAMES),
        "position_coefficients": coefficients,
        "training_rows_by_position": counts,
        "training_row_count": len(normalized),
        "training_source_manifest_sha256": _canonical_sha256(source_rows),
        "ridge_lambda": float(ridge_lambda),
        "validation_status": "UNVALIDATED_CANDIDATE",
        "promotion_authority": False,
        "market_inputs_consumed": False,
        "requires_walk_forward_validation": True,
    }
    artifact["artifact_sha256"] = _canonical_sha256(artifact)
    return artifact


def validate_cfb_participation_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CFBParticipationModelError("CFB_PARTICIPATION_ARTIFACT_SCHEMA_INVALID")
    if str(payload.get("sport") or "").upper() != "CFB":
        raise CFBParticipationModelError("CFB_PARTICIPATION_ARTIFACT_SPORT_INVALID")
    if payload.get("promotion_authority") is not False or payload.get("market_inputs_consumed") is not False:
        raise CFBParticipationModelError("CFB_PARTICIPATION_ARTIFACT_AUTHORITY_INVALID")
    if payload.get("validation_status") != "UNVALIDATED_CANDIDATE":
        raise CFBParticipationModelError("CFB_PARTICIPATION_ARTIFACT_STATUS_INVALID")
    if tuple(payload.get("feature_names") or ()) != FEATURE_NAMES:
        raise CFBParticipationModelError("CFB_PARTICIPATION_FEATURE_CONTRACT_MISMATCH")
    coefficients = payload.get("position_coefficients")
    if not isinstance(coefficients, Mapping) or "QB" not in coefficients:
        raise CFBParticipationModelError("CFB_PARTICIPATION_COEFFICIENTS_REQUIRED")
    normalized_coefficients: dict[str, tuple[float, ...]] = {}
    for raw_group, raw_values in coefficients.items():
        group = _position_group(raw_group)
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)) or len(raw_values) != len(FEATURE_NAMES):
            raise CFBParticipationModelError(f"CFB_PARTICIPATION_COEFFICIENT_COUNT_INVALID:{group}")
        normalized_coefficients[group] = tuple(
            _finite(value, f"CFB_PARTICIPATION_COEFFICIENT_INVALID:{group}") for value in raw_values
        )
    _hex64(payload.get("training_source_manifest_sha256"), "CFB_PARTICIPATION_TRAINING_MANIFEST_SHA_INVALID")
    actual_sha = _canonical_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})
    if _hex64(payload.get("artifact_sha256"), "CFB_PARTICIPATION_ARTIFACT_SHA_INVALID") != actual_sha:
        raise CFBParticipationModelError("CFB_PARTICIPATION_ARTIFACT_SHA_MISMATCH")
    out = dict(payload)
    out["position_coefficients"] = normalized_coefficients
    return out


def starter_retention_probability(
    artifact: Mapping[str, Any],
    *,
    position_group: str,
    quarter: int,
    clock_seconds_remaining: int,
    score_margin: float,
) -> float:
    model = validate_cfb_participation_artifact(artifact)
    group = _position_group(position_group)
    coefficients = model["position_coefficients"].get(group)
    if coefficients is None:
        raise CFBParticipationModelError(f"CFB_PARTICIPATION_POSITION_MODEL_MISSING:{group}")
    features = _features(
        quarter=quarter,
        clock_seconds_remaining=clock_seconds_remaining,
        score_margin=score_margin,
    )
    logit = float(features @ np.asarray(coefficients, dtype=float))
    if logit >= 0:
        z = exp(-min(logit, 35.0))
        return float(1.0 / (1.0 + z))
    z = exp(max(logit, -35.0))
    return float(z / (1.0 + z))


__all__ = [
    "CFBParticipationModelError",
    "FEATURE_NAMES",
    "POSITION_GROUPS",
    "SCHEMA_VERSION",
    "fit_cfb_participation_model",
    "starter_retention_probability",
    "validate_cfb_participation_artifact",
]
