"""Prospective-only evidence validation for the NFL M2 V2F research candidate.

This module validates chronology, identity, and provenance only. It cannot promote
markets, create Model_P, change eligibility, or authorize bets.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

from .m2_v2f_candidate import NFL_M2_V2F_CANDIDATE_MODEL_ID

POLICY_SCHEMA = "NFL_V2F_FORWARD_VALIDATION_POLICY_V1"
FORBIDDEN_PROVENANCE = {"synthetic", "reconstructed", "backfilled", "inferred", "derived_from_result"}
EXPECTED_CANDIDATE_CODE_GIT_SHA = "3b6cdb1461aeda46a822eb820b39bb5155e30201"
EXPECTED_CANDIDATE_SOURCE_BLOB_SHA1 = "52919be92dbea82a12f7d03c8214265c63aa1f55"


class NFLV2FForwardEvidenceError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NFLV2FForwardEvidenceError(code)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLV2FForwardEvidenceError(f"NFL_V2F_FORWARD_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None, f"NFL_V2F_FORWARD_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed


def _sha(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == 64 and all(c in "0123456789abcdef" for c in text), f"NFL_V2F_FORWARD_SHA256_INVALID:{field}")
    return text


def _git_sha(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == 40 and all(c in "0123456789abcdef" for c in text), f"NFL_V2F_FORWARD_GIT_SHA_INVALID:{field}")
    return text


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(policy, Mapping), "NFL_V2F_FORWARD_POLICY_MAPPING_REQUIRED")
    _require(policy.get("schema") == POLICY_SCHEMA, "NFL_V2F_FORWARD_POLICY_SCHEMA_INVALID")
    _require(policy.get("candidate_id") == NFL_M2_V2F_CANDIDATE_MODEL_ID, "NFL_V2F_FORWARD_POLICY_CANDIDATE_ID_MISMATCH")
    prereg_sha = _git_sha(policy.get("preregistration_commit_sha"), "policy.preregistration_commit_sha")
    prereg_ts = _timestamp(policy.get("preregistration_timestamp_utc"), "policy.preregistration_timestamp_utc")
    allowed = tuple(str(x) for x in policy.get("allowed_markets") or ())
    _require(allowed == ("MONEYLINE", "SPREAD", "TOTAL"), "NFL_V2F_FORWARD_POLICY_MARKETS_INVALID")
    params = policy.get("candidate_model_parameters")
    _require(isinstance(params, Mapping), "NFL_V2F_FORWARD_POLICY_PARAMETERS_REQUIRED")
    _require(float(params.get("ridge_alpha")) == 10.0, "NFL_V2F_FORWARD_POLICY_RIDGE_CHANGED")
    _require(float(params.get("home_kernel_scale")) == 1.0, "NFL_V2F_FORWARD_POLICY_HOME_KERNEL_CHANGED")
    _require(float(params.get("away_kernel_scale")) == 1.0, "NFL_V2F_FORWARD_POLICY_AWAY_KERNEL_CHANGED")
    _require(params.get("hyperparameter_search_allowed") is False, "NFL_V2F_FORWARD_POLICY_SEARCH_MUST_BE_FALSE")
    _require(policy.get("promotion_authority") is False, "NFL_V2F_FORWARD_POLICY_PROMOTION_FORBIDDEN")
    _require(policy.get("may_change_market_eligibility") is False, "NFL_V2F_FORWARD_POLICY_ELIGIBILITY_FORBIDDEN")
    _require(policy.get("may_create_model_p") is False, "NFL_V2F_FORWARD_POLICY_MODEL_P_FORBIDDEN")
    _require(policy.get("official_bet_authorized") is False, "NFL_V2F_FORWARD_POLICY_OFFICIAL_FORBIDDEN")
    return {"preregistration_commit_sha": prereg_sha, "preregistration_timestamp": prereg_ts, "allowed_markets": allowed}


def _provenance(row: Mapping[str, Any], prefix: str) -> tuple[str, str]:
    provenance = str(row.get(f"{prefix}_provenance") or "").strip().lower()
    _require(bool(provenance), f"NFL_V2F_FORWARD_PROVENANCE_REQUIRED:{prefix}")
    _require(provenance not in FORBIDDEN_PROVENANCE, f"NFL_V2F_FORWARD_PROVENANCE_FORBIDDEN:{prefix}")
    return provenance, _sha(row.get(f"{prefix}_sha256"), f"{prefix}_sha256")


def validate_forward_row(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    p = validate_policy(policy)
    _require(isinstance(row, Mapping), "NFL_V2F_FORWARD_ROW_MAPPING_REQUIRED")
    _require(row.get("candidate_id") == NFL_M2_V2F_CANDIDATE_MODEL_ID, "NFL_V2F_FORWARD_CANDIDATE_ID_MISMATCH")
    _require(_git_sha(row.get("preregistration_commit_sha"), "row.preregistration_commit_sha") == p["preregistration_commit_sha"], "NFL_V2F_FORWARD_PREREG_SHA_MISMATCH")
    code_sha = _git_sha(row.get("candidate_code_git_sha"), "row.candidate_code_git_sha")
    _require(code_sha == EXPECTED_CANDIDATE_CODE_GIT_SHA, "NFL_V2F_FORWARD_CANDIDATE_CODE_SHA_MISMATCH")
    source_blob = _git_sha(row.get("candidate_source_blob_sha1"), "row.candidate_source_blob_sha1")
    _require(source_blob == EXPECTED_CANDIDATE_SOURCE_BLOB_SHA1, "NFL_V2F_FORWARD_CANDIDATE_SOURCE_BLOB_MISMATCH")
    event_id = str(row.get("event_id") or "").strip()
    market = str(row.get("market") or "").strip().upper()
    selection = str(row.get("selection") or "").strip()
    book = str(row.get("book") or "").strip()
    _require(bool(event_id and selection and book), "NFL_V2F_FORWARD_IDENTITY_REQUIRED")
    _require(market in p["allowed_markets"], "NFL_V2F_FORWARD_MARKET_INVALID")

    start = _timestamp(row.get("event_start_utc"), "event_start_utc")
    prediction_ts = _timestamp(row.get("prediction_captured_at_utc"), "prediction_captured_at_utc")
    decision_ts = _timestamp(row.get("decision_quote_captured_at_utc"), "decision_quote_captured_at_utc")
    close_ts = _timestamp(row.get("close_quote_captured_at_utc"), "close_quote_captured_at_utc")
    outcome_ts = _timestamp(row.get("final_outcome_observed_at_utc"), "final_outcome_observed_at_utc")
    freeze = p["preregistration_timestamp"]
    _require(start > freeze, "NFL_V2F_FORWARD_EVENT_NOT_PROSPECTIVE")
    _require(freeze < prediction_ts < start, "NFL_V2F_FORWARD_PREDICTION_TIME_INVALID")
    _require(freeze < decision_ts < close_ts < start, "NFL_V2F_FORWARD_MARKET_TIME_INVALID")
    _require(outcome_ts >= start, "NFL_V2F_FORWARD_OUTCOME_TIME_INVALID")

    for prefix in ("prediction", "decision_quote", "close_quote", "final_result"):
        _provenance(row, prefix)

    probability = float(row.get("model_probability"))
    _require(isfinite(probability) and 0.0 <= probability <= 1.0, "NFL_V2F_FORWARD_MODEL_PROBABILITY_INVALID")
    threshold = row.get("threshold")
    if market == "MONEYLINE":
        _require(threshold is None, "NFL_V2F_FORWARD_MONEYLINE_THRESHOLD_MUST_BE_NULL")
    else:
        try:
            numeric_threshold = float(threshold)
        except (TypeError, ValueError) as exc:
            raise NFLV2FForwardEvidenceError("NFL_V2F_FORWARD_THRESHOLD_INVALID") from exc
        _require(isfinite(numeric_threshold), "NFL_V2F_FORWARD_THRESHOLD_INVALID")

    normalized = {
        "candidate_id": NFL_M2_V2F_CANDIDATE_MODEL_ID,
        "preregistration_commit_sha": p["preregistration_commit_sha"],
        "candidate_code_git_sha": code_sha,
        "candidate_source_blob_sha1": source_blob,
        "event_id": event_id,
        "market": market,
        "selection": selection,
        "threshold": threshold,
        "book": book,
        "event_start_utc": start.isoformat(),
        "prediction_captured_at_utc": prediction_ts.isoformat(),
        "decision_quote_captured_at_utc": decision_ts.isoformat(),
        "close_quote_captured_at_utc": close_ts.isoformat(),
        "final_outcome_observed_at_utc": outcome_ts.isoformat(),
        "model_probability": probability,
        "prediction_sha256": _sha(row.get("prediction_sha256"), "prediction_sha256"),
        "decision_quote_sha256": _sha(row.get("decision_quote_sha256"), "decision_quote_sha256"),
        "close_quote_sha256": _sha(row.get("close_quote_sha256"), "close_quote_sha256"),
        "final_result_sha256": _sha(row.get("final_result_sha256"), "final_result_sha256"),
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**normalized, "evidence_row_sha256": sha256(canonical).hexdigest()}


def audit_forward_rows(rows: Iterable[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    valid: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows):
        try:
            normalized = validate_forward_row(row, policy)
            identity = (normalized["event_id"], normalized["market"], normalized["selection"], normalized["threshold"], normalized["book"])
            _require(identity not in seen, "NFL_V2F_FORWARD_DUPLICATE_OBSERVATION")
            seen.add(identity)
            valid.append(normalized)
        except (NFLV2FForwardEvidenceError, TypeError, ValueError) as exc:
            failures.append({"index": index, "reason": str(exc)})
    count = len(valid)
    reached = max((n for n in (50, 100, 150) if count >= n), default=0)
    canonical = json.dumps(valid, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": "NFL_V2F_FORWARD_EVIDENCE_AUDIT_V1",
        "status": "PROSPECTIVE_EVIDENCE_VALID" if valid and not failures else "BLOCKED_PROSPECTIVE_EVIDENCE",
        "valid_observation_count": count,
        "invalid_observation_count": len(failures),
        "highest_checkpoint_reached": reached,
        "promotion_authority": False,
        "may_change_market_eligibility": False,
        "prospective_rows_sha256": sha256(canonical).hexdigest(),
        "failures": failures,
    }
