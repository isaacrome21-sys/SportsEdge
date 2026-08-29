"""Pre-Truth-Gate validation attestation for SportsEdge CFB.

This is intentionally separate from CFB_TRUTH_GATE_V1. It does not weaken or silently
change the frozen numerical gate. Instead, it proves that the evidence being handed to
the gate was generated under the required PIT, calibration, benchmark and coverage
contracts. Quote-sync policy identity is carried by the prediction policy bundle while
this fold artifact attests that the quote-sync check actually passed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping


ATTESTATION_ID = "CFB_VALIDATION_ATTESTATION_V1_1"
REQUIRED_CHECKS = (
    "pit_leakage",
    "market_blind_feature_scan",
    "entity_registry",
    "prior_decay_fold_integrity",
    "opponent_adjust_fold_integrity",
    "calibration_fold_integrity",
    "oof_residual_fold_integrity",
    "key_number_calibration",
    "quote_sync_policy",
    "mode_identity",
    "game_coverage_accounting",
    "market_coverage_accounting",
    "benchmark_replayability",
    "historical_data_readiness",
    "shadow_live_firewall",
)


class CFBValidationAttestationError(ValueError):
    pass


def _sha(value: str, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBValidationAttestationError(f"{field}:SHA256_REQUIRED")
    return text


@dataclass(frozen=True)
class CFBValidationAttestation:
    market: str
    test_season: int
    checks: Mapping[str, bool]
    evidence_ids: Mapping[str, str]
    validation_policy_sha: str
    feature_source_policy_sha: str
    entity_registry_sha: str
    benchmark_methodology_sha: str
    prior_decay_sha: str
    model_artifact_sha: str
    calibrator_artifact_sha: str
    simulation_artifact_sha: str
    attestation_id: str = ATTESTATION_ID

    def validate(self) -> "CFBValidationAttestation":
        if self.attestation_id != ATTESTATION_ID:
            raise CFBValidationAttestationError("ATTESTATION_ID_INVALID")
        if str(self.market).upper() not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBValidationAttestationError("ATTESTATION_MARKET_INVALID")
        if isinstance(self.test_season, bool) or int(self.test_season) < 1900:
            raise CFBValidationAttestationError("ATTESTATION_TEST_SEASON_INVALID")
        if set(self.checks) != set(REQUIRED_CHECKS):
            missing = sorted(set(REQUIRED_CHECKS) - set(self.checks))
            extra = sorted(set(self.checks) - set(REQUIRED_CHECKS))
            raise CFBValidationAttestationError(
                "ATTESTATION_CHECK_SET_INVALID:missing=" + ",".join(missing) + ";extra=" + ",".join(extra)
            )
        for name, value in self.checks.items():
            if type(value) is not bool:
                raise CFBValidationAttestationError(f"ATTESTATION_CHECK_BOOL_REQUIRED:{name}")
        if set(self.evidence_ids) != set(REQUIRED_CHECKS):
            raise CFBValidationAttestationError("ATTESTATION_EVIDENCE_ID_SET_INVALID")
        if any(not str(value).strip() for value in self.evidence_ids.values()):
            raise CFBValidationAttestationError("ATTESTATION_EVIDENCE_ID_REQUIRED")
        for field in (
            "validation_policy_sha", "feature_source_policy_sha", "entity_registry_sha",
            "benchmark_methodology_sha", "prior_decay_sha", "model_artifact_sha",
            "calibrator_artifact_sha", "simulation_artifact_sha",
        ):
            _sha(getattr(self, field), field)
        return self

    @property
    def passed(self) -> bool:
        self.validate()
        return all(bool(self.checks[name]) for name in REQUIRED_CHECKS)

    def require_pass(self) -> "CFBValidationAttestation":
        if not self.passed:
            failures = [name for name in REQUIRED_CHECKS if not self.checks[name]]
            raise CFBValidationAttestationError("CFB_VALIDATION_ATTESTATION_FAILED:" + ",".join(failures))
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        payload = asdict(self)
        payload["market"] = str(self.market).upper()
        payload["test_season"] = int(self.test_season)
        payload["checks"] = {name: bool(self.checks[name]) for name in REQUIRED_CHECKS}
        payload["evidence_ids"] = {name: str(self.evidence_ids[name]) for name in REQUIRED_CHECKS}
        return payload

    def content_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def assert_attestations_cover_forward_seasons(
    attestations: list[CFBValidationAttestation],
    *,
    market: str,
    expected_test_seasons: list[int],
) -> str:
    target = str(market).upper()
    rows = [a.require_pass() for a in attestations if str(a.market).upper() == target]
    actual = sorted(int(a.test_season) for a in rows)
    expected = sorted(int(x) for x in expected_test_seasons)
    if actual != expected:
        raise CFBValidationAttestationError(
            f"ATTESTATION_FORWARD_SEASON_COVERAGE_MISMATCH:expected={expected}:actual={actual}"
        )
    hashes = [a.content_hash() for a in sorted(rows, key=lambda a: a.test_season)]
    raw = json.dumps(hashes, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()
