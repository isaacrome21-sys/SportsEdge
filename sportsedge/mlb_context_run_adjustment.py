"""Apply only frozen, validated MLB context coefficients to run means.

This serving seam is inert unless an artifact explicitly has status=VALIDATED
and matches the frozen feature schema. No market price is accepted.
"""
from __future__ import annotations

from math import exp, isfinite
from typing import Any, Mapping

from .mlb_context_model_features import SCHEMA_VERSION

ARTIFACT_VERSION = "mlb_context_run_adjustment_artifact_v1"


class MLBContextArtifactError(RuntimeError):
    pass


def apply_validated_run_adjustment(
    away_mean: float,
    home_mean: float,
    context: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> tuple[float, float, dict[str, Any]]:
    if artifact is None:
        return (
            float(away_mean),
            float(home_mean),
            {"status": "BASELINE", "reason": "NO_VALIDATED_ARTIFACT"},
        )
    if (
        artifact.get("artifact_version") != ARTIFACT_VERSION
        or artifact.get("status") != "VALIDATED"
    ):
        raise MLBContextArtifactError("context artifact is not validated")
    if artifact.get("feature_schema_version") != SCHEMA_VERSION:
        raise MLBContextArtifactError("context artifact feature schema mismatch")

    coeffs = artifact.get("coefficients")
    if not isinstance(coeffs, Mapping):
        raise MLBContextArtifactError("missing coefficient mapping")
    features = context.get("features") if isinstance(context, Mapping) else None
    if not isinstance(features, Mapping):
        return (
            float(away_mean),
            float(home_mean),
            {"status": "BASELINE", "reason": "NO_ELIGIBLE_CONTEXT"},
        )

    log_mult = 0.0
    used: dict[str, dict[str, float]] = {}
    for key, raw_beta in coeffs.items():
        value = features.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            beta = float(raw_beta)
            x = float(value)
        except (TypeError, ValueError):
            continue
        if not isfinite(beta) or not isfinite(x):
            continue
        log_mult += beta * x
        used[str(key)] = {"value": x, "coefficient": beta}

    cap = float(artifact.get("max_abs_log_multiplier", 0.20))
    if not isfinite(cap) or cap <= 0:
        raise MLBContextArtifactError("invalid context multiplier cap")
    log_mult = max(-cap, min(cap, log_mult))
    mult = exp(log_mult)
    return (
        float(away_mean) * mult,
        float(home_mean) * mult,
        {
            "status": "CONTEXT_ADJUSTED",
            "multiplier": mult,
            "features_used": used,
            "artifact_id": artifact.get("artifact_id"),
        },
    )
