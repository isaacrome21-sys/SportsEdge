"""Audit-hardening contracts for SportsEdge CFB v1.2.

These contracts are deliberately independent of sportsbook/provider implementation.
They make point-in-time provenance, board/market coverage, narrative overrides and
prediction provenance machine-checkable and fail closed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from string import hexdigits
from typing import Any, Iterable, Mapping


class CFBAuditContractError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBAuditContractError(f"{field}:TIMESTAMP_REQUIRED")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBAuditContractError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBAuditContractError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CFBAuditContractError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBAuditContractError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBAuditContractError(f"{field}:FINITE_REQUIRED")
    return out


def _sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in hexdigits.lower() for ch in text):
        raise CFBAuditContractError(f"{field}:SHA256_REQUIRED")
    return text


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class PITObservation:
    """Point-in-time envelope for one feature-source observation."""

    source_id: str
    source_version: str
    source_asof_ts: str
    feature_asof_ts: str
    ingested_ts: str
    game_start_ts: str
    max_latency_seconds: int
    provenance_id: str

    def validate(self) -> "PITObservation":
        source_ts = _utc(self.source_asof_ts, "source_asof_ts")
        feature_ts = _utc(self.feature_asof_ts, "feature_asof_ts")
        ingested_ts = _utc(self.ingested_ts, "ingested_ts")
        game_ts = _utc(self.game_start_ts, "game_start_ts")
        if not str(self.source_id).strip() or not str(self.source_version).strip():
            raise CFBAuditContractError("SOURCE_IDENTITY_REQUIRED")
        if not str(self.provenance_id).strip():
            raise CFBAuditContractError("PROVENANCE_ID_REQUIRED")
        if isinstance(self.max_latency_seconds, bool) or int(self.max_latency_seconds) < 0:
            raise CFBAuditContractError("MAX_LATENCY_INVALID")
        if source_ts > feature_ts:
            raise CFBAuditContractError("SOURCE_ASOF_AFTER_FEATURE_ASOF")
        if feature_ts >= game_ts:
            raise CFBAuditContractError("FEATURE_ASOF_NOT_BEFORE_GAME")
        if source_ts >= game_ts:
            raise CFBAuditContractError("SOURCE_ASOF_NOT_BEFORE_GAME")
        latency = (ingested_ts - source_ts).total_seconds()
        if latency < 0:
            raise CFBAuditContractError("INGESTED_BEFORE_SOURCE_ASOF")
        if latency > int(self.max_latency_seconds):
            raise CFBAuditContractError("SOURCE_LATENCY_EXCEEDED")
        return self


@dataclass(frozen=True)
class CFBOverride:
    override_id: str
    created_at: str
    game_id: str
    mode: str
    reason_code: str
    evidence_refs: tuple[str, ...]
    action: str

    def validate(self) -> "CFBOverride":
        _utc(self.created_at, "override.created_at")
        mode = str(self.mode).upper()
        action = str(self.action).upper()
        if mode not in {"MANUAL", "HYBRID"}:
            raise CFBAuditContractError("NARRATIVE_OVERRIDE_MODE_FORBIDDEN")
        if action not in {"BLOCK", "DOWNGRADE", "NO_CHANGE"}:
            raise CFBAuditContractError("NARRATIVE_OVERRIDE_ACTION_FORBIDDEN")
        if not self.override_id or not self.game_id or not self.reason_code:
            raise CFBAuditContractError("OVERRIDE_IDENTITY_REQUIRED")
        if not self.evidence_refs:
            raise CFBAuditContractError("OVERRIDE_EVIDENCE_REQUIRED")
        return self


@dataclass(frozen=True)
class CoverageItem:
    game_id: str
    classification: str
    status: str
    reason: str | None = None

    def validate(self) -> "CoverageItem":
        if not self.game_id:
            raise CFBAuditContractError("COVERAGE_GAME_ID_REQUIRED")
        if self.classification not in {"FBS_FBS", "FBS_FCS", "FCS_FCS"}:
            raise CFBAuditContractError("COVERAGE_CLASSIFICATION_INVALID")
        if self.status not in {"SCORED", "BLOCKED", "UNAVAILABLE"}:
            raise CFBAuditContractError("COVERAGE_STATUS_INVALID")
        if self.status != "SCORED" and not str(self.reason or "").strip():
            raise CFBAuditContractError("COVERAGE_REASON_REQUIRED")
        return self


@dataclass(frozen=True)
class CoverageReport:
    expected_game_ids: tuple[str, ...]
    items: tuple[CoverageItem, ...]

    def validate(self) -> "CoverageReport":
        expected = tuple(str(x) for x in self.expected_game_ids)
        if len(expected) != len(set(expected)):
            raise CFBAuditContractError("COVERAGE_EXPECTED_DUPLICATE")
        for item in self.items:
            item.validate()
        actual = tuple(item.game_id for item in self.items)
        if len(actual) != len(set(actual)):
            raise CFBAuditContractError("COVERAGE_ITEM_DUPLICATE")
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            raise CFBAuditContractError("COVERAGE_SILENT_DROP:" + ",".join(missing))
        if extra:
            raise CFBAuditContractError("COVERAGE_UNEXPECTED_GAME:" + ",".join(extra))
        return self

    @property
    def coverage_ok(self) -> bool:
        self.validate()
        return True

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"expected_game_ids": list(self.expected_game_ids), "items": [asdict(x) for x in self.items]}

    def content_hash(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True)
class MarketCoverageItem:
    game_id: str
    market: str
    status: str
    reason: str | None = None

    def validate(self) -> "MarketCoverageItem":
        if not self.game_id:
            raise CFBAuditContractError("MARKET_COVERAGE_GAME_ID_REQUIRED")
        if self.market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBAuditContractError("MARKET_COVERAGE_MARKET_INVALID")
        if self.status not in {"PRICED", "BLOCKED", "UNAVAILABLE"}:
            raise CFBAuditContractError("MARKET_COVERAGE_STATUS_INVALID")
        if self.status != "PRICED" and not str(self.reason or "").strip():
            raise CFBAuditContractError("MARKET_COVERAGE_REASON_REQUIRED")
        return self


@dataclass(frozen=True)
class MarketCoverageReport:
    expected_contracts: tuple[tuple[str, str], ...]
    items: tuple[MarketCoverageItem, ...]

    def validate(self) -> "MarketCoverageReport":
        expected = tuple((str(g), str(m).upper()) for g, m in self.expected_contracts)
        if len(expected) != len(set(expected)):
            raise CFBAuditContractError("MARKET_COVERAGE_EXPECTED_DUPLICATE")
        for item in self.items:
            item.validate()
        actual = tuple((item.game_id, item.market) for item in self.items)
        if len(actual) != len(set(actual)):
            raise CFBAuditContractError("MARKET_COVERAGE_ITEM_DUPLICATE")
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            raise CFBAuditContractError("MARKET_COVERAGE_SILENT_DROP:" + ",".join(f"{g}:{m}" for g, m in missing))
        if extra:
            raise CFBAuditContractError("MARKET_COVERAGE_UNEXPECTED:" + ",".join(f"{g}:{m}" for g, m in extra))
        return self

    @property
    def accounting_ok(self) -> bool:
        self.validate()
        return True

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "expected_contracts": [{"game_id": g, "market": m} for g, m in self.expected_contracts],
            "items": [asdict(x) for x in self.items],
        }

    def content_hash(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True)
class CFBAuditManifest:
    sport: str
    game_id: str
    market: str
    selection: str
    model_version: str
    feature_version: str
    calibrator_version: str
    simulation_version: str
    prior_version: str
    decay_schedule_hash: str
    variance_model_version: str
    key_number_method: str
    data_cutoff: str
    feature_asof_ts: str
    odds_snapshot_id: str
    market_benchmark_id: str
    coverage_report_id: str
    market_coverage_report_id: str
    book: str
    line: float | None
    price: float
    quote_timestamp: str
    decision_timestamp: str
    model_p: float
    no_vig_market_p: float
    edge: float
    ev: float
    kelly: float
    historical_gate_status: str
    live_decision: str
    spec_sha: str
    policy_sha: str
    benchmark_methodology_sha: str
    exposure_sha: str
    market_context_sha: str
    feature_source_policy_sha: str
    quote_sync_policy_sha: str
    model_promotion_policy_sha: str
    entity_registry_sha: str
    validation_attestation_sha: str
    decision_provenance_sha: str
    override_id: str | None = None

    def validate(self) -> "CFBAuditManifest":
        if self.sport != "CFB":
            raise CFBAuditContractError("MANIFEST_SPORT_INVALID")
        if self.market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            raise CFBAuditContractError("MANIFEST_MARKET_INVALID")
        for field in ("data_cutoff", "feature_asof_ts", "quote_timestamp", "decision_timestamp"):
            _utc(getattr(self, field), field)
        if _utc(self.feature_asof_ts, "feature_asof_ts") >= _utc(self.decision_timestamp, "decision_timestamp"):
            raise CFBAuditContractError("FEATURE_ASOF_AFTER_DECISION")
        if _utc(self.quote_timestamp, "quote_timestamp") > _utc(self.decision_timestamp, "decision_timestamp"):
            raise CFBAuditContractError("QUOTE_AFTER_DECISION")
        for field in ("model_p", "no_vig_market_p"):
            value = _finite(getattr(self, field), field)
            if not 0.0 <= value <= 1.0:
                raise CFBAuditContractError(f"{field}:PROBABILITY_RANGE")
        for field in ("price", "edge", "ev", "kelly"):
            _finite(getattr(self, field), field)
        if self.kelly < 0.0:
            raise CFBAuditContractError("kelly:NEGATIVE")
        if self.line is not None:
            _finite(self.line, "line")
        sha_fields = (
            "spec_sha", "policy_sha", "benchmark_methodology_sha", "exposure_sha",
            "market_context_sha", "feature_source_policy_sha", "quote_sync_policy_sha",
            "model_promotion_policy_sha", "entity_registry_sha", "validation_attestation_sha",
            "decision_provenance_sha", "decay_schedule_hash",
        )
        for field in sha_fields:
            _sha256(getattr(self, field), field)
        if not self.coverage_report_id or not self.market_coverage_report_id:
            raise CFBAuditContractError("MANIFEST_COVERAGE_IDS_REQUIRED")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def content_hash(self) -> str:
        return canonical_sha256(self.to_dict())


def assert_mode_identity(payloads: Mapping[str, Mapping[str, Any]], *, ignored_fields: Iterable[str] = ()) -> None:
    """Require identical mathematical outputs across Manual/Hybrid/Automatic modes."""

    required = {"MANUAL", "HYBRID", "AUTOMATIC"}
    if set(payloads) != required:
        raise CFBAuditContractError("MODE_IDENTITY_ALL_THREE_REQUIRED")
    ignored = set(str(x) for x in ignored_fields)
    normalized: dict[str, dict[str, Any]] = {}
    for mode, payload in payloads.items():
        normalized[mode] = {k: v for k, v in dict(payload).items() if k not in ignored and k != "mode"}
    hashes = {mode: canonical_sha256(value) for mode, value in normalized.items()}
    if len(set(hashes.values())) != 1:
        raise CFBAuditContractError("MODE_MATHEMATICAL_IDENTITY_FAILED")
