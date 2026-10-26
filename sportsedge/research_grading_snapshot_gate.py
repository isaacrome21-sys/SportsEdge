"""Fail-closed research audit of separate pregame entry and closing quote snapshots.

This module does not compute EV, CLV, probabilities, or betting recommendations.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation


REQUIRED_SNAPSHOT = ("snapshot_id", "captured_at", "book", "event_id", "market", "contract_id", "offers")


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp is not a string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp has no timezone")
    return result


def _valid_snapshot(snapshot, selection):
    if not isinstance(snapshot, dict) or any(not snapshot.get(k) for k in REQUIRED_SNAPSHOT):
        return False
    # The source contract ID must encode period, selection pair and exact line.
    if not isinstance(snapshot["contract_id"], str) or not snapshot["contract_id"].strip():
        return False
    offers = snapshot["offers"]
    if not isinstance(offers, dict) or len(offers) != 2 or selection not in offers:
        return False
    for value in offers.values():
        try:
            odds = Decimal(str(value))
            if not odds.is_finite() or odds != odds.to_integral_value() or abs(odds) < 100:
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False
    return True


def audit_grading_snapshots(*, entry, close, selection, evaluated_at, event_start):
    """Return quote age admission and CLV readiness, never derived EV/CLV.

    evaluated_at is the historical time at which the pick was priced.
    A later close is allowed only before kickoff, and never serves as entry.
    """
    refused = {"admission": "REFUSED", "clv_ready": False}
    if not isinstance(selection, str) or not selection or not _valid_snapshot(entry, selection):
        return {**refused, "reason": "ENTRY_INCOMPLETE_OR_UNPAIRED"}
    try:
        capture = _time(entry["captured_at"])
        evaluated = _time(evaluated_at)
        start = _time(event_start)
    except (ValueError, TypeError, OverflowError):
        return {**refused, "reason": "INVALID_TIME"}
    if capture > evaluated:
        return {**refused, "reason": "FUTURE_DATED_ENTRY"}
    if capture >= start or evaluated >= start:
        return {**refused, "reason": "POSTSTART_ENTRY_OR_EVALUATION"}
    age_seconds = (evaluated - capture).total_seconds()
    if age_seconds > 300:
        return {**refused, "reason": "ENTRY_OLDER_THAN_300S"}
    admission = "ELIGIBLE_QUOTE" if age_seconds <= 150 else "RESEARCH_AGED_QUOTE"
    result = {"admission": admission, "quote_age_seconds": age_seconds, "clv_ready": False}
    if close is None:
        return {**result, "reason": "CLOSE_MISSING"}
    if not _valid_snapshot(close, selection):
        return {**result, "reason": "CLOSE_INCOMPLETE_OR_UNPAIRED"}
    if close["snapshot_id"] == entry["snapshot_id"]:
        return {**result, "reason": "SELF_CLOSING_SNAPSHOT"}
    for field in ("book", "event_id", "market"):
        if entry[field] != close[field]:
            return {**result, "reason": "CROSS_SOURCE_OR_MARKET_CLOSE"}
    if entry["contract_id"] != close["contract_id"]:
        return {**result, "reason": "CROSS_CONTRACT_CLOSE"}
    if set(entry["offers"]) != set(close["offers"]):
        return {**result, "reason": "CLOSE_OFFER_SIDES_MISMATCH"}
    try:
        closing_time = _time(close["captured_at"])
    except (ValueError, TypeError, OverflowError):
        return {**result, "reason": "INVALID_CLOSE_TIME"}
    if closing_time <= capture or closing_time >= start:
        return {**result, "reason": "CLOSE_NOT_DISTINCT_LATER_PRESTART"}
    if closing_time <= evaluated:
        return {**result, "reason": "CLOSE_NOT_LATER_THAN_EVALUATION"}
    if admission != "ELIGIBLE_QUOTE":
        return {**result, "reason": "RESEARCH_AGED_QUOTE_NOT_FORWARD_ELIGIBLE"}
    return {**result, "clv_ready": True, "reason": "SEPARATE_PREGAME_CLOSE_CONFIRMED"}
