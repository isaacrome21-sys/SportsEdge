"""Deterministic CFB policy bundle hashing.

Config JSON is hashed canonically so whitespace-only edits do not alter policy identity.
The specification markdown is hashed as raw bytes because prose changes are governance
changes even when machine policy is unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


class CFBPolicyBundleError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def canonical_json_sha256(path: str | Path) -> str:
    file = Path(path)
    if not file.is_file():
        raise CFBPolicyBundleError(f"POLICY_FILE_MISSING:{file}")
    try:
        payload: Any = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBPolicyBundleError(f"POLICY_JSON_INVALID:{file}") from exc
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha256_bytes(raw)


def raw_file_sha256(path: str | Path) -> str:
    file = Path(path)
    if not file.is_file():
        raise CFBPolicyBundleError(f"POLICY_FILE_MISSING:{file}")
    return _sha256_bytes(file.read_bytes())


def _validate_sha(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBPolicyBundleError(f"{field}:SHA256_REQUIRED")
    return text


@dataclass(frozen=True)
class CFBPolicyBundle:
    spec_sha: str
    truth_gate_sha: str
    benchmark_methodology_sha: str
    exposure_sha: str
    market_context_sha: str
    feature_source_policy_sha: str
    validation_policy_sha: str
    quote_sync_policy_sha: str
    model_promotion_policy_sha: str
    entity_registry_sha: str

    def validate(self) -> "CFBPolicyBundle":
        for field, value in asdict(self).items():
            _validate_sha(value, field)
        return self

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {key: str(value) for key, value in asdict(self).items()}

    def bundle_sha(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _sha256_bytes(raw)


def load_cfb_policy_bundle(repo_root: str | Path, *, entity_registry_sha: str) -> CFBPolicyBundle:
    root = Path(repo_root)
    return CFBPolicyBundle(
        spec_sha=raw_file_sha256(root / "docs" / "CFB_AUDIT_SPEC_V1_2.md"),
        truth_gate_sha=canonical_json_sha256(root / "config" / "cfb_truth_gate_v1.json"),
        benchmark_methodology_sha=canonical_json_sha256(root / "config" / "cfb_market_benchmark_v1.json"),
        exposure_sha=canonical_json_sha256(root / "config" / "cfb_exposure_v1.json"),
        market_context_sha=canonical_json_sha256(root / "config" / "cfb_market_context_v1.json"),
        feature_source_policy_sha=canonical_json_sha256(root / "config" / "cfb_feature_source_policy_v1.json"),
        validation_policy_sha=canonical_json_sha256(root / "config" / "cfb_validation_policy_v1.json"),
        quote_sync_policy_sha=canonical_json_sha256(root / "config" / "cfb_quote_sync_v1.json"),
        model_promotion_policy_sha=canonical_json_sha256(root / "config" / "cfb_model_v2_promotion_v1.json"),
        entity_registry_sha=_validate_sha(entity_registry_sha, "entity_registry_sha"),
    ).validate()
