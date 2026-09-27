"""Research-only PIT-safe MLB plate-umpire called-strike tendency.

Methodology:
1. Join Baseball Savant taken pitches to home-plate umpire assignments by game_pk.
2. Exclude every pitch whose game_date is on/after the target date.
3. Fit a pooled logistic expected-called-strike model from normalized pitch location.
4. For each umpire, compute observed minus expected called-strike probability.
5. Shrink that residual toward zero and require a minimum called-pitch sample.

This is deliberately separate from market prices and from Model_P promotion. A raw
called-strike rate is not used because pitch-location mix materially affects it.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

import numpy as np

SOURCE = "BASEBALL_SAVANT_STATCAST_PLUS_STATSAPI_HP_UMPIRE"
SCHEMA_VERSION = "mlb_umpire_zone_tendency_v1"
MODEL_VERSION = "zone_logit_residual_v1"
CALLED_DESCRIPTIONS = frozenset({"called_strike", "ball"})
DEFAULT_MIN_CALLED_PITCHES = 200
DEFAULT_PRIOR_EQUIVALENT_PITCHES = 500
DEFAULT_L2 = 1e-4


class MLBUmpireZoneTendencyError(ValueError):
    pass


def _content_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int(value: Any) -> int | None:
    value_f = _float(value)
    return int(value_f) if value_f is not None else None


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_game_umpires(value: Mapping[Any, Any] | Iterable[Mapping[str, Any]]) -> dict[int, int]:
    """Return game_pk -> home-plate umpire id from a mapping or row iterable."""
    out: dict[int, int] = {}
    if isinstance(value, Mapping):
        items = value.items()
        for game_raw, ump_raw in items:
            game_pk = _int(game_raw)
            if isinstance(ump_raw, Mapping):
                umpire_id = _int(
                    ump_raw.get("umpire_id")
                    or ump_raw.get("hp_umpire_id")
                    or ump_raw.get("plate_umpire_id")
                )
            else:
                umpire_id = _int(ump_raw)
            if game_pk is not None and umpire_id is not None:
                out[game_pk] = umpire_id
        return out

    for row in value:
        if not isinstance(row, Mapping):
            continue
        game_pk = _int(row.get("game_pk") or row.get("gamePk"))
        umpire_id = _int(
            row.get("umpire_id")
            or row.get("hp_umpire_id")
            or row.get("plate_umpire_id")
        )
        if game_pk is not None and umpire_id is not None:
            out[game_pk] = umpire_id
    return out


def _zone_features(row: Mapping[str, Any]) -> tuple[float, ...] | None:
    plate_x = _float(row.get("plate_x"))
    plate_z = _float(row.get("plate_z"))
    sz_top = _float(row.get("sz_top"))
    sz_bot = _float(row.get("sz_bot"))
    if None in {plate_x, plate_z, sz_top, sz_bot}:
        return None
    assert plate_x is not None and plate_z is not None and sz_top is not None and sz_bot is not None
    height = sz_top - sz_bot
    if not math.isfinite(height) or abs(height) < 1e-9:
        return None
    z_norm = (plate_z - sz_bot) / height
    if not math.isfinite(z_norm):
        return None
    return (
        plate_x,
        plate_x * plate_x,
        z_norm,
        z_norm * z_norm,
        plate_x * z_norm,
        abs(plate_x),
        abs(z_norm - 0.5),
    )


def prepare_called_pitches(
    pitch_rows: Iterable[Mapping[str, Any]],
    *,
    game_umpires: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter to prior-date taken pitches with valid locations and HP assignment."""
    assignments = normalize_game_umpires(game_umpires)
    selected: list[dict[str, Any]] = []
    counts = {
        "input_rows": 0,
        "future_or_target_date_excluded": 0,
        "non_taken_excluded": 0,
        "missing_location_excluded": 0,
        "missing_umpire_assignment_excluded": 0,
        "invalid_game_date_excluded": 0,
    }
    for raw in pitch_rows:
        counts["input_rows"] += 1
        if not isinstance(raw, Mapping):
            counts["missing_location_excluded"] += 1
            continue
        description = str(raw.get("description") or "").strip().lower()
        if description not in CALLED_DESCRIPTIONS:
            counts["non_taken_excluded"] += 1
            continue
        game_day = _date(raw.get("game_date"))
        if game_day is None:
            counts["invalid_game_date_excluded"] += 1
            continue
        if game_day >= target_date:
            counts["future_or_target_date_excluded"] += 1
            continue
        game_pk = _int(raw.get("game_pk"))
        umpire_id = assignments.get(game_pk) if game_pk is not None else None
        if umpire_id is None:
            counts["missing_umpire_assignment_excluded"] += 1
            continue
        features = _zone_features(raw)
        if features is None:
            counts["missing_location_excluded"] += 1
            continue
        selected.append({
            "game_pk": int(game_pk),
            "game_date": game_day.isoformat(),
            "umpire_id": int(umpire_id),
            "description": description,
            "observed_strike": 1.0 if description == "called_strike" else 0.0,
            "features": features,
        })
    return selected, counts


def fit_expected_called_strike_model(
    called_rows: Iterable[Mapping[str, Any]],
    *,
    l2: float = DEFAULT_L2,
    max_iter: int = 60,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Fit a deterministic ridge logistic zone model with NumPy Newton steps."""
    rows = list(called_rows)
    if len(rows) < 2:
        raise MLBUmpireZoneTendencyError("INSUFFICIENT_CALLED_PITCHES_FOR_ZONE_MODEL")
    X_core = np.asarray([row["features"] for row in rows], dtype=float)
    y = np.asarray([float(row["observed_strike"]) for row in rows], dtype=float)
    if X_core.ndim != 2 or X_core.shape[1] != 7:
        raise MLBUmpireZoneTendencyError("INVALID_ZONE_FEATURE_MATRIX")
    if len(np.unique(y)) < 2:
        raise MLBUmpireZoneTendencyError("ZONE_MODEL_REQUIRES_BOTH_BALLS_AND_STRIKES")

    X = np.column_stack([X_core, np.ones(X_core.shape[0], dtype=float)])
    beta = np.zeros(X.shape[1], dtype=float)
    penalty = np.ones(X.shape[1], dtype=float) * float(l2)
    penalty[-1] = 0.0  # never penalize intercept
    converged = False

    for iteration in range(1, int(max_iter) + 1):
        z = np.clip(X @ beta, -30.0, 30.0)
        p = 1.0 / (1.0 + np.exp(-z))
        weights = np.clip(p * (1.0 - p), 1e-8, None)
        grad = (X.T @ (p - y)) / len(y) + penalty * beta
        hessian = ((X.T * weights) @ X) / len(y) + np.diag(penalty)
        hessian += np.eye(hessian.shape[0]) * 1e-10
        try:
            step = np.linalg.solve(hessian, grad)
        except np.linalg.LinAlgError as exc:
            raise MLBUmpireZoneTendencyError("ZONE_MODEL_SINGULAR_HESSIAN") from exc
        beta -= step
        if float(np.max(np.abs(step))) <= float(tolerance):
            converged = True
            break

    z = np.clip(X @ beta, -30.0, 30.0)
    p = np.clip(1.0 / (1.0 + np.exp(-z)), 1e-12, 1.0 - 1e-12)
    log_loss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    return {
        "model_version": MODEL_VERSION,
        "feature_names": [
            "plate_x", "plate_x_sq", "z_norm", "z_norm_sq",
            "plate_x_z_norm", "abs_plate_x", "abs_z_dev",
        ],
        "coefficients": [float(x) for x in beta[:-1]],
        "intercept": float(beta[-1]),
        "n_called_pitches": len(rows),
        "log_loss": round(log_loss, 8),
        "l2": float(l2),
        "iterations": iteration,
        "converged": converged,
    }


def _expected_probability(features: Iterable[float], model: Mapping[str, Any]) -> float:
    coef = np.asarray(model["coefficients"], dtype=float)
    x = np.asarray(list(features), dtype=float)
    z = float(np.clip(x @ coef + float(model["intercept"]), -30.0, 30.0))
    return float(1.0 / (1.0 + math.exp(-z)))


def build_umpire_zone_tendency(
    *,
    pitch_rows: Iterable[Mapping[str, Any]],
    game_umpires: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
    umpire_id: int,
    min_called_pitches: int = DEFAULT_MIN_CALLED_PITCHES,
    prior_equivalent_pitches: int = DEFAULT_PRIOR_EQUIVALENT_PITCHES,
) -> dict[str, Any]:
    if int(min_called_pitches) < 1 or int(prior_equivalent_pitches) < 1:
        raise MLBUmpireZoneTendencyError("INVALID_SAMPLE_POLICY")
    selected, exclusions = prepare_called_pitches(
        pitch_rows,
        game_umpires=game_umpires,
        target_date=target_date,
    )
    if len(selected) < 2:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "source": SOURCE,
            "target_date": target_date.isoformat(),
            "umpire_id": int(umpire_id),
            "status": "MISSING_PRIOR_CALLED_PITCHES",
            "called_strike_tendency": None,
            "model_p_eligible": False,
            "exclusions": exclusions,
        }

    model = fit_expected_called_strike_model(selected)
    target_rows = [row for row in selected if int(row["umpire_id"]) == int(umpire_id)]
    source_rows = [
        {
            "game_pk": row["game_pk"],
            "game_date": row["game_date"],
            "umpire_id": row["umpire_id"],
            "description": row["description"],
            "features": [round(float(x), 8) for x in row["features"]],
        }
        for row in selected
    ]
    source_sha = _content_sha(source_rows)
    if not target_rows:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "source": SOURCE,
            "target_date": target_date.isoformat(),
            "umpire_id": int(umpire_id),
            "status": "MISSING_UMPIRE_HISTORY",
            "called_strike_tendency": None,
            "model_p_eligible": False,
            "pooled_model": model,
            "source_subset_sha256": source_sha,
            "prior_pitch_count": len(selected),
            "exclusions": exclusions,
        }

    observed = float(np.mean([row["observed_strike"] for row in target_rows]))
    expected = float(np.mean([
        _expected_probability(row["features"], model) for row in target_rows
    ]))
    raw_bias = observed - expected
    n = len(target_rows)
    shrink_weight = n / (n + int(prior_equivalent_pitches))
    shrunk_bias = raw_bias * shrink_weight
    sample_pass = n >= int(min_called_pitches)

    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "source": SOURCE,
        "target_date": target_date.isoformat(),
        "umpire_id": int(umpire_id),
        "status": "AVAILABLE" if sample_pass else "BELOW_MIN_CALLED_PITCHES",
        "sample_gate": "PASS" if sample_pass else "BELOW_MIN_CALLED_PITCHES",
        "min_called_pitches": int(min_called_pitches),
        "prior_equivalent_pitches": int(prior_equivalent_pitches),
        "umpire_called_pitches": n,
        "prior_pitch_count": len(selected),
        "observed_called_strike_rate": round(observed, 6),
        "expected_called_strike_rate": round(expected, 6),
        "raw_called_strike_bias": round(raw_bias, 6),
        "shrink_weight": round(shrink_weight, 6),
        "shrunk_called_strike_bias": round(shrunk_bias, 6),
        "called_strike_tendency": round(shrunk_bias, 6) if sample_pass else None,
        "pooled_model": model,
        "source_subset_sha256": source_sha,
        "exclusions": exclusions,
        "model_p_eligible": False,
        "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
    }
