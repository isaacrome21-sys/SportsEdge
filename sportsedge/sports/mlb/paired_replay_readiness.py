"""Fail-closed readiness checks for MLB historical decision/close market evidence.

This module validates evidence availability only.  It cannot create Model_P,
promotion evidence, Truth Gate PASS, edge floors, or market eligibility.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "mlb_paired_replay_readiness_v1"
FORBIDDEN_PROVENANCE = {"synthetic", "reconstructed", "backfilled", "inferred", "derived_from_result"}


class MLBPairedReplayReadinessError(ValueError):
    pass


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBPairedReplayReadinessError(f"MLB_PAIRED_REPLAY_TIMESTAMP_INVALID:{field}") from exc
    if parsed.tzinfo is None:
        raise MLBPairedReplayReadinessError(f"MLB_PAIRED_REPLAY_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed


def _require(value: bool, error: str) -> None:
    if not value:
        raise MLBPairedReplayReadinessError(error)


def _price(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBPairedReplayReadinessError(f"MLB_PAIRED_REPLAY_PRICE_INVALID:{field}") from exc
    _require(isfinite(number) and number != 0.0, f"MLB_PAIRED_REPLAY_PRICE_INVALID:{field}")
    return number


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    values = tuple(str(row.get(k) or "").strip() for k in ("event_id", "market", "selection", "book"))
    _require(all(values), "MLB_PAIRED_REPLAY_IDENTITY_REQUIRED")
    return values


def _validate_quote(row: Mapping[str, Any], *, stage: str, event_start: datetime) -> dict[str, Any]:
    _require(isinstance(row, Mapping), f"MLB_PAIRED_REPLAY_{stage.upper()}_MAPPING_REQUIRED")
    identity = _identity(row)
    observed = _ts(row.get("observed_at"), f"{stage}.observed_at")
    _require(observed < event_start, f"MLB_PAIRED_REPLAY_{stage.upper()}_AFTER_START")
    provenance = str(row.get("provenance") or "").strip().lower()
    _require(bool(provenance), f"MLB_PAIRED_REPLAY_{stage.upper()}_PROVENANCE_REQUIRED")
    _require(provenance not in FORBIDDEN_PROVENANCE, f"MLB_PAIRED_REPLAY_{stage.upper()}_PROVENANCE_FORBIDDEN")
    source_sha = str(row.get("source_sha256") or "").strip().lower()
    _require(len(source_sha) == 64 and all(c in "0123456789abcdef" for c in source_sha), f"MLB_PAIRED_REPLAY_{stage.upper()}_SOURCE_SHA256_INVALID")
    return {
        "identity": identity,
        "observed_at": observed,
        "price": _price(row.get("price"), f"{stage}.price"),
        "source_sha256": source_sha,
        "provenance": provenance,
    }


def validate_decision_close_pair(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one genuine PIT decision/close pair without granting promotion authority."""
    _require(isinstance(pair, Mapping), "MLB_PAIRED_REPLAY_PAIR_MAPPING_REQUIRED")
    event_start = _ts(pair.get("event_start"), "event_start")
    decision = _validate_quote(pair.get("decision"), stage="decision", event_start=event_start)
    close = _validate_quote(pair.get("close"), stage="close", event_start=event_start)
    _require(decision["identity"] == close["identity"], "MLB_PAIRED_REPLAY_IDENTITY_MISMATCH")
    _require(decision["observed_at"] < close["observed_at"], "MLB_PAIRED_REPLAY_TEMPORAL_ORDER_INVALID")
    payload = {
        "event_id": decision["identity"][0],
        "market": decision["identity"][1],
        "selection": decision["identity"][2],
        "book": decision["identity"][3],
        "event_start": event_start.isoformat(),
        "decision_observed_at": decision["observed_at"].isoformat(),
        "close_observed_at": close["observed_at"].isoformat(),
        "decision_price": decision["price"],
        "close_price": close["price"],
        "decision_source_sha256": decision["source_sha256"],
        "close_source_sha256": close["source_sha256"],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "pair_sha256": sha256(canonical).hexdigest()}


def audit_paired_replay_readiness(pairs: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        try:
            valid.append(validate_decision_close_pair(pair))
        except MLBPairedReplayReadinessError as exc:
            failures.append({"index": index, "reason": str(exc)})
    canonical = json.dumps(valid, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_FOR_REPLAY" if valid and not failures else "BLOCKED_PAIRED_MARKET_EVIDENCE",
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "valid_pair_count": len(valid),
        "invalid_pair_count": len(failures),
        "valid_pairs_sha256": sha256(canonical).hexdigest(),
        "failures": failures,
    }
