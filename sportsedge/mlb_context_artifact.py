"""Build a fail-closed MLB context candidate artifact from PIT validation output."""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

from .mlb_context_model_features import SCHEMA_VERSION
from .mlb_context_run_adjustment import ARTIFACT_VERSION


def build_candidate_artifact(
    coefficients: Mapping[str, float],
    validation: Mapping[str, Any],
    *,
    source_manifest: Mapping[str, Any],
    max_abs_log_multiplier: float = 0.20,
) -> dict[str, Any]:
    if validation.get("status") != "VALIDATED":
        raise ValueError("refusing artifact: temporal validation did not pass")
    if (
        not source_manifest.get("pit_strict")
        or source_manifest.get("contains_sportsbook_prices")
    ):
        raise ValueError("refusing artifact: source manifest is not PIT/price blind")

    cap = float(max_abs_log_multiplier)
    if not isfinite(cap) or cap <= 0:
        raise ValueError("refusing artifact: invalid multiplier cap")

    frozen_coefficients: dict[str, float] = {}
    for key, value in sorted(coefficients.items()):
        beta = float(value)
        if not isfinite(beta):
            raise ValueError("refusing artifact: non-finite coefficient")
        frozen_coefficients[str(key)] = beta

    body = {
        "artifact_version": ARTIFACT_VERSION,
        "feature_schema_version": SCHEMA_VERSION,
        "status": "VALIDATED",
        "coefficients": frozen_coefficients,
        "max_abs_log_multiplier": cap,
        "validation": dict(validation),
        "source_manifest": dict(source_manifest),
    }
    raw = json.dumps(
        body, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    body["artifact_id"] = "sha256:" + sha256(raw).hexdigest()
    return body
