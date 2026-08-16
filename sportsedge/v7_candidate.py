from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from typing import Any, Mapping

from .source_lineage import canonical_json_sha256
from .v7_baseball_features import assert_no_market_contamination

V7_CANDIDATE_SCHEMA_VERSION = "mlb_v7_candidate_v1"


class V7CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class LinearLogitCandidate:
    model_name: str
    feature_contract_sha256: str
    intercept: float
    coefficients: Mapping[str, float]
    candidate_sha256: str


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise V7CandidateError(f"{field} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V7CandidateError(f"{field} must be numeric") from exc
    if not isfinite(out):
        raise V7CandidateError(f"{field} must be finite")
    return out


def _flatten_numeric(value: Mapping[str, Any], prefix: str = "") -> dict[str, float]:
    assert_no_market_contamination(value)
    out: dict[str, float] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, Mapping):
            out.update(_flatten_numeric(child, path))
        elif isinstance(child, bool):
            out[path] = float(child)
        elif isinstance(child, (int, float)):
            out[path] = _finite(child, path)
    return out


def load_candidate(artifact: Mapping[str, Any]) -> LinearLogitCandidate:
    required = {"schema_version", "model_name", "feature_contract_sha256", "intercept", "coefficients", "candidate_sha256"}
    missing = sorted(required - set(artifact))
    if missing:
        raise V7CandidateError(f"missing candidate fields: {missing}")
    if artifact["schema_version"] != V7_CANDIDATE_SCHEMA_VERSION:
        raise V7CandidateError("candidate schema version mismatch")
    coeffs_raw = artifact["coefficients"]
    if not isinstance(coeffs_raw, Mapping) or not coeffs_raw:
        raise V7CandidateError("coefficients must be a non-empty object")
    coeffs = {str(k): _finite(v, f"coefficient:{k}") for k, v in coeffs_raw.items()}
    canonical = {
        "schema_version": V7_CANDIDATE_SCHEMA_VERSION,
        "model_name": str(artifact["model_name"]),
        "feature_contract_sha256": str(artifact["feature_contract_sha256"]),
        "intercept": _finite(artifact["intercept"], "intercept"),
        "coefficients": coeffs,
    }
    expected = canonical_json_sha256(canonical)
    if str(artifact["candidate_sha256"]) != expected:
        raise V7CandidateError("candidate hash mismatch")
    return LinearLogitCandidate(
        model_name=canonical["model_name"],
        feature_contract_sha256=canonical["feature_contract_sha256"],
        intercept=canonical["intercept"], coefficients=coeffs,
        candidate_sha256=expected,
    )


def score_candidate(candidate: LinearLogitCandidate, feature_payload: Mapping[str, Any]) -> float:
    feature_hash = str(feature_payload.get("feature_contract_sha256") or "")
    if feature_hash != candidate.feature_contract_sha256:
        raise V7CandidateError("feature contract hash mismatch")
    flat = _flatten_numeric(feature_payload)
    missing = sorted(set(candidate.coefficients) - set(flat))
    if missing:
        raise V7CandidateError(f"missing model features: {missing}")
    z = candidate.intercept + sum(candidate.coefficients[k] * flat[k] for k in candidate.coefficients)
    if z >= 0:
        return 1.0 / (1.0 + exp(-z))
    ez = exp(z)
    return ez / (1.0 + ez)


def build_candidate_artifact(*, model_name: str, feature_contract_sha256: str, intercept: Any, coefficients: Mapping[str, Any]) -> dict[str, Any]:
    artifact = {
        "schema_version": V7_CANDIDATE_SCHEMA_VERSION,
        "model_name": str(model_name),
        "feature_contract_sha256": str(feature_contract_sha256),
        "intercept": _finite(intercept, "intercept"),
        "coefficients": {str(k): _finite(v, f"coefficient:{k}") for k, v in coefficients.items()},
    }
    if not artifact["coefficients"]:
        raise V7CandidateError("coefficients must be non-empty")
    artifact["candidate_sha256"] = canonical_json_sha256(artifact)
    return artifact
