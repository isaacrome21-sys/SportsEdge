#!/usr/bin/env python3
"""Append-only manual execution evidence for stale-price radar candidates.

This logger does not place wagers. It records what actually happened after a human
attempted a candidate: durable fill, changed-price fill, rejection, or later void.
Persistence observations are deliberately insufficient for this record type.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v2.json"
RECORD_TYPE = "MARKET_MAKER_RADAR_EXECUTION_ATTEMPT_V1"
CANDIDATE_TYPE = "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1"


class ExecutionAttemptError(ValueError):
    pass


def _number(value: Any, field: str, *, allow_none: bool = False) -> float | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_INVALID") from exc
    if not math.isfinite(out):
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_INVALID")
    return out


def _ts(value: Any, field: str, *, allow_none: bool = False) -> datetime | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_REQUIRED")
    text = str(value).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_INVALID") from exc
    if out.tzinfo is None:
        raise ExecutionAttemptError(f"RADAR_EXECUTION_{field.upper()}_TIMEZONE_REQUIRED")
    return out.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_record(candidate: Mapping[str, Any], attempt: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    if candidate.get("record_type") != CANDIDATE_TYPE:
        raise ExecutionAttemptError("RADAR_EXECUTION_CANDIDATE_TYPE_INVALID")
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ExecutionAttemptError("RADAR_EXECUTION_CANDIDATE_ID_REQUIRED")
    supplied_candidate = str(attempt.get("candidate_id") or candidate_id).strip()
    if supplied_candidate != candidate_id:
        raise ExecutionAttemptError("RADAR_EXECUTION_CANDIDATE_ID_MISMATCH")

    outcome = str(attempt.get("outcome") or "").strip().upper()
    allowed = set(policy["takeability"]["execution_outcomes"])
    if outcome not in allowed:
        raise ExecutionAttemptError("RADAR_EXECUTION_OUTCOME_INVALID")

    attempted_at = _ts(attempt.get("attempted_at"), "attempted_at")
    filled_at = _ts(attempt.get("filled_at"), "filled_at", allow_none=True)
    voided_at = _ts(attempt.get("voided_at"), "voided_at", allow_none=True)
    attempted_price = _number(attempt.get("attempted_price_american"), "attempted_price_american")
    filled_price = _number(attempt.get("filled_price_american"), "filled_price_american", allow_none=True)
    requested = _number(attempt.get("stake_requested_units"), "stake_requested_units")
    accepted = _number(attempt.get("stake_accepted_units"), "stake_accepted_units")
    if requested <= 0:
        raise ExecutionAttemptError("RADAR_EXECUTION_STAKE_REQUESTED_MUST_BE_POSITIVE")
    if accepted < 0 or accepted > requested:
        raise ExecutionAttemptError("RADAR_EXECUTION_STAKE_ACCEPTED_OUT_OF_RANGE")

    durable = outcome in {"FILLED", "FILLED_AT_CHANGED_PRICE"}
    if outcome == "REJECTED":
        if accepted != 0 or filled_price is not None or filled_at is not None or voided_at is not None:
            raise ExecutionAttemptError("RADAR_EXECUTION_REJECTED_FIELDS_CONTRADICT_OUTCOME")
    else:
        if accepted <= 0 or filled_price is None or filled_at is None:
            raise ExecutionAttemptError("RADAR_EXECUTION_ACCEPTED_FILL_FIELDS_REQUIRED")
        if filled_at < attempted_at:
            raise ExecutionAttemptError("RADAR_EXECUTION_FILLED_BEFORE_ATTEMPT")

    if outcome == "FILLED" and not math.isclose(float(filled_price), float(attempted_price), abs_tol=1e-9):
        raise ExecutionAttemptError("RADAR_EXECUTION_CHANGED_PRICE_REQUIRES_CHANGED_PRICE_OUTCOME")
    if outcome == "FILLED_AT_CHANGED_PRICE" and math.isclose(float(filled_price), float(attempted_price), abs_tol=1e-9):
        raise ExecutionAttemptError("RADAR_EXECUTION_CHANGED_PRICE_OUTCOME_REQUIRES_PRICE_CHANGE")
    if outcome == "VOIDED_AFTER_ACCEPTANCE":
        if voided_at is None:
            raise ExecutionAttemptError("RADAR_EXECUTION_VOIDED_AT_REQUIRED")
        if filled_at is not None and voided_at < filled_at:
            raise ExecutionAttemptError("RADAR_EXECUTION_VOID_BEFORE_ACCEPTANCE")
    elif voided_at is not None:
        raise ExecutionAttemptError("RADAR_EXECUTION_VOIDED_AT_CONTRADICTS_OUTCOME")

    book = str(candidate.get("soft_book") or "").lower()
    attempt_id = hashlib.sha256(f"{candidate_id}|{book}|{_iso(attempted_at)}".encode("utf-8")).hexdigest()[:24]
    reason = attempt.get("outcome_reason")
    return {
        "record_type": RECORD_TYPE,
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "attempt_id": attempt_id,
        "candidate_id": candidate_id,
        "source_family_id": candidate.get("source_family_id"),
        "event_id": candidate.get("event_id"),
        "market": candidate.get("market"),
        "outcome_name": candidate.get("outcome"),
        "point": candidate.get("point"),
        "soft_book": book,
        "candidate_created_at": candidate.get("candidate_created_at"),
        "offered_price_american": candidate.get("offered_price_american"),
        "attempted_price_american": attempted_price,
        "filled_price_american": filled_price,
        "stake_requested_units": requested,
        "stake_accepted_units": accepted,
        "stake_acceptance_ratio": accepted / requested,
        "attempted_at": _iso(attempted_at),
        "filled_at": _iso(filled_at),
        "voided_at": _iso(voided_at),
        "outcome": outcome,
        "outcome_reason": None if reason is None else str(reason),
        "durable_fill": durable,
        "execution_evidence": True,
        "persistence_proxy": False,
        "model_p_authority": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "automatic_wager_authority": False
    }


def record_path(root: Path, record: Mapping[str, Any]) -> Path:
    return root / "archive" / "market-maker-radar" / "execution-attempts" / str(record["soft_book"]) / f"{record['candidate_id']}.json"


def persist(root: Path, record: Mapping[str, Any]) -> Path:
    target = record_path(root, record)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ExecutionAttemptError("RADAR_EXECUTION_ATTEMPT_ALREADY_RECORDED_FOR_CANDIDATE")
    target.write_text(json.dumps(dict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--attempt", required=True, help="JSON file containing the observed execution outcome")
    parser.add_argument("--out-root", required=True)
    args = parser.parse_args(argv)
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    attempt = json.loads(Path(args.attempt).read_text(encoding="utf-8"))
    record = build_record(candidate, attempt, policy)
    target = persist(Path(args.out_root), record)
    print(json.dumps({"state": "RECORDED", "path": str(target), "record": record}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
