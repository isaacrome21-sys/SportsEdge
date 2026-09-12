"""Fail-closed readiness validation for MLB paired historical market evidence.

This module validates whether historical decision/close quote pairs are reproducible
inputs for the frozen MLB replay lane. It does not create Model_P, calculate edge,
change eligibility, or grant promotion authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from .replay_policy import EXPECTED_POLICY_ID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
PAIR_MAX_SKEW_SECONDS = 30
REQUIRED_PROVENANCE = "OBSERVED_PIT"


class MLBPairedMarketEvidenceError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MLBPairedMarketEvidenceError(reason)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MLBPairedMarketEvidenceError(f"MLB_PAIRED_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None, f"MLB_PAIRED_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def _sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    _require(bool(_SHA256.fullmatch(text)), f"MLB_PAIRED_SHA256_INVALID:{field}")
    return text


def _snapshot(snapshot: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    _require(isinstance(snapshot, Mapping), f"MLB_PAIRED_SNAPSHOT_REQUIRED:{label}")
    _require(snapshot.get("provenance") == REQUIRED_PROVENANCE, f"MLB_PAIRED_PROVENANCE_INVALID:{label}")
    _require(snapshot.get("reconstructed") is False, f"MLB_PAIRED_RECONSTRUCTED_FORBIDDEN:{label}")
    _require(snapshot.get("post_result_substitution") is False, f"MLB_PAIRED_POST_RESULT_SUBSTITUTION_FORBIDDEN:{label}")
    _require(snapshot.get("imputed") is False, f"MLB_PAIRED_IMPUTED_FORBIDDEN:{label}")
    _sha(snapshot.get("source_sha256"), f"{label}.source_sha256")

    sides = snapshot.get("sides")
    _require(isinstance(sides, list) and len(sides) == 2, f"MLB_PAIRED_TWO_SIDES_REQUIRED:{label}")
    side_names: set[str] = set()
    observed: list[datetime] = []
    thresholds: list[Any] = []
    for index, raw in enumerate(sides):
        _require(isinstance(raw, Mapping), f"MLB_PAIRED_SIDE_INVALID:{label}:{index}")
        side = str(raw.get("side") or "").strip()
        _require(bool(side) and side not in side_names, f"MLB_PAIRED_SIDE_IDENTITY_INVALID:{label}:{index}")
        side_names.add(side)
        price = raw.get("price")
        _require(isinstance(price, (int, float)) and not isinstance(price, bool), f"MLB_PAIRED_PRICE_INVALID:{label}:{side}")
        _require(float(price) != 0.0, f"MLB_PAIRED_PRICE_INVALID:{label}:{side}")
        observed.append(_timestamp(raw.get("observed_at"), f"{label}.sides[{index}].observed_at"))
        thresholds.append(raw.get("threshold"))

    skew = abs((max(observed) - min(observed)).total_seconds())
    _require(skew <= PAIR_MAX_SKEW_SECONDS, f"MLB_PAIRED_SIDE_TIMESTAMP_SKEW:{label}")
    _require(thresholds[0] == thresholds[1], f"MLB_PAIRED_THRESHOLD_MISMATCH:{label}")
    return {
        "observed_at": max(observed),
        "threshold": thresholds[0],
        "side_names": tuple(sorted(side_names)),
        "source_sha256": str(snapshot["source_sha256"]).lower(),
    }


def validate_paired_market_evidence(
    payload: Mapping[str, Any],
    *,
    policy_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one historical decision/close pair for replay readiness only."""
    _require(isinstance(payload, Mapping), "MLB_PAIRED_EVIDENCE_MAPPING_REQUIRED")
    _require(policy_identity.get("policy_id") == EXPECTED_POLICY_ID, "MLB_PAIRED_POLICY_ID_MISMATCH")
    policy_sha = _sha(policy_identity.get("policy_sha256"), "policy_identity.policy_sha256")
    _require(payload.get("replay_policy_id") == EXPECTED_POLICY_ID, "MLB_PAIRED_POLICY_BINDING_ID_MISMATCH")
    _require(str(payload.get("replay_policy_sha256") or "").lower() == policy_sha, "MLB_PAIRED_POLICY_BINDING_SHA_MISMATCH")

    for field in ("game_id", "market_id", "book", "source"):
        _require(bool(str(payload.get(field) or "").strip()), f"MLB_PAIRED_IDENTITY_REQUIRED:{field}")
    _sha(payload.get("feature_source_sha256"), "feature_source_sha256")
    game_start = _timestamp(payload.get("game_start"), "game_start")

    decision = _snapshot(payload.get("decision"), label="decision")
    close = _snapshot(payload.get("close"), label="close")
    _require(decision["observed_at"] < close["observed_at"], "MLB_PAIRED_DECISION_NOT_BEFORE_CLOSE")
    _require(close["observed_at"] < game_start, "MLB_PAIRED_CLOSE_NOT_PREGAME")
    _require(decision["side_names"] == close["side_names"], "MLB_PAIRED_SIDE_IDENTITY_MISMATCH")
    _require(decision["threshold"] == close["threshold"], "MLB_PAIRED_DECISION_CLOSE_THRESHOLD_MISMATCH")

    for label in ("decision", "close"):
        snapshot = payload[label]
        for field in ("game_id", "market_id", "book"):
            _require(snapshot.get(field) == payload.get(field), f"MLB_PAIRED_SNAPSHOT_IDENTITY_MISMATCH:{label}:{field}")

    return {
        "status": "READY_FOR_REPLAY",
        "reason": "PAIRED_PIT_DECISION_AND_CLOSE_REPRODUCIBLE",
        "game_id": str(payload["game_id"]),
        "market_id": str(payload["market_id"]),
        "book": str(payload["book"]),
        "replay_policy_id": EXPECTED_POLICY_ID,
        "replay_policy_sha256": policy_sha,
        "feature_source_sha256": str(payload["feature_source_sha256"]).lower(),
        "decision_source_sha256": decision["source_sha256"],
        "close_source_sha256": close["source_sha256"],
        "promotion_authority": False,
        "eligible": False,
    }
