"""Content-addressable decision provenance for SportsEdge.

Every decision must identify the exact model code/artifact, feature schema, calibrator,
simulation artifact/seed policy, sport policy, benchmark methodology and evidence gate.
This is independent of acquisition mode so Manual and Hybrid can be replayed identically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from string import hexdigits


class DecisionProvenanceError(ValueError):
    pass


def _sha(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in hexdigits.lower() for ch in text):
        raise DecisionProvenanceError(f"{field}:SHA256_REQUIRED")
    return text


@dataclass(frozen=True)
class DecisionProvenance:
    sport: str
    mode: str
    model_code_sha: str
    model_artifact_sha: str
    feature_schema_version: str
    feature_schema_sha: str
    calibrator_sha: str
    simulation_artifact_sha: str
    seed_policy: str
    policy_sha: str
    benchmark_methodology_sha: str
    evidence_gate_sha: str
    data_cutoff: str

    def validate(self) -> "DecisionProvenance":
        if str(self.mode).upper() not in {"MANUAL", "HYBRID", "AUTOMATIC"}:
            raise DecisionProvenanceError("MODE_INVALID")
        if not str(self.sport).strip() or not str(self.feature_schema_version).strip():
            raise DecisionProvenanceError("SPORT_AND_FEATURE_SCHEMA_VERSION_REQUIRED")
        if not str(self.seed_policy).strip() or not str(self.data_cutoff).strip():
            raise DecisionProvenanceError("SEED_POLICY_AND_DATA_CUTOFF_REQUIRED")
        for field in (
            "model_code_sha",
            "model_artifact_sha",
            "feature_schema_sha",
            "calibrator_sha",
            "simulation_artifact_sha",
            "policy_sha",
            "benchmark_methodology_sha",
            "evidence_gate_sha",
        ):
            _sha(getattr(self, field), field)
        return self

    def model_bundle_hash(self) -> str:
        self.validate()
        payload = {
            "model_code_sha": self.model_code_sha.lower(),
            "model_artifact_sha": self.model_artifact_sha.lower(),
            "feature_schema_version": self.feature_schema_version,
            "feature_schema_sha": self.feature_schema_sha.lower(),
            "calibrator_sha": self.calibrator_sha.lower(),
            "simulation_artifact_sha": self.simulation_artifact_sha.lower(),
            "seed_policy": self.seed_policy,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()

    def content_hash(self) -> str:
        self.validate()
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def require_same_math_identity(left: DecisionProvenance, right: DecisionProvenance) -> None:
    left.validate(); right.validate()
    if left.sport != right.sport:
        raise DecisionProvenanceError("SPORT_MISMATCH")
    if left.model_bundle_hash() != right.model_bundle_hash():
        raise DecisionProvenanceError("MODEL_BUNDLE_MISMATCH")
    if left.policy_sha.lower() != right.policy_sha.lower():
        raise DecisionProvenanceError("POLICY_SHA_MISMATCH")
    if left.benchmark_methodology_sha.lower() != right.benchmark_methodology_sha.lower():
        raise DecisionProvenanceError("BENCHMARK_SHA_MISMATCH")
    if left.evidence_gate_sha.lower() != right.evidence_gate_sha.lower():
        raise DecisionProvenanceError("EVIDENCE_GATE_SHA_MISMATCH")
