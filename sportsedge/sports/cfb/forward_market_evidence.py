"""Fail-closed CFB prospective decision/close market-evidence validation.

Market evidence is deliberately separate from predictive source snapshots. A valid
pair proves only that exact pregame sportsbook quotes were captured and byte-bound;
it cannot create Model_P, promotion authority, eligibility, staking, or OFFICIAL
status by itself.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "SPORTSEDGE_CFB_FORWARD_MARKET_PAIR_V1"
_ALLOWED_MARKETS = {"MONEYLINE", "SPREAD", "TOTAL"}
_FORBIDDEN_PROVENANCE = ("synthetic", "reconstructed", "backfilled", "inferred", "derived_from_result")


def _time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label}_TIMEZONE_MISSING")
    return parsed


def _sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _safe_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    candidate = root / rel
    try:
        if not candidate.resolve().is_relative_to(root.resolve()):
            return None
    except OSError:
        return None
    return candidate


def _price(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number != 0.0


def audit_cfb_forward_market_pair(pair_path: Path) -> dict[str, Any]:
    """Validate one immutable prospective CFB decision/close quote pair."""
    try:
        raw = pair_path.read_bytes()
        payload = json.loads(raw)
    except OSError as exc:
        raise ValueError("PAIR_READ_FAILED") from exc
    except Exception as exc:
        raise ValueError("PAIR_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("PAIR_OBJECT_REQUIRED")

    reasons: list[str] = []
    if payload.get("schema_version") != SCHEMA:
        reasons.append("SCHEMA_INVALID")
    if str(payload.get("sport") or "").upper() != "CFB":
        reasons.append("SPORT_MISMATCH")
    for field in ("promotion_authority", "may_create_model_p", "eligibility_changed", "official_status_granted"):
        if payload.get(field) is not False:
            reasons.append(f"{field.upper()}_MUST_BE_FALSE")

    identity = payload.get("identity")
    if not isinstance(identity, dict):
        reasons.append("IDENTITY_MISSING")
        identity = {}
    event_id = str(identity.get("event_id") or "").strip()
    book = str(identity.get("book") or "").strip()
    market = str(identity.get("market") or "").upper()
    selection = str(identity.get("selection") or "").strip()
    if not event_id:
        reasons.append("EVENT_ID_MISSING")
    if not book:
        reasons.append("BOOK_MISSING")
    if market not in _ALLOWED_MARKETS:
        reasons.append("MARKET_INVALID")
    if not selection:
        reasons.append("SELECTION_MISSING")
    threshold = identity.get("threshold")
    if market == "MONEYLINE" and threshold is not None:
        reasons.append("MONEYLINE_THRESHOLD_FORBIDDEN")
    if market in {"SPREAD", "TOTAL"}:
        try:
            threshold_num = float(threshold)
            if not math.isfinite(threshold_num):
                raise ValueError
        except (TypeError, ValueError):
            reasons.append("THRESHOLD_INVALID")

    try:
        kickoff = _time(payload.get("kickoff_utc"), "KICKOFF")
    except ValueError as exc:
        reasons.append(str(exc))
        kickoff = None

    root = pair_path.parent
    quote_times: dict[str, tuple[datetime, datetime] | None] = {}
    for label in ("decision", "close"):
        quote = payload.get(label)
        if not isinstance(quote, dict):
            reasons.append(f"{label.upper()}_MISSING")
            quote_times[label] = None
            continue
        for field, expected in (("event_id", event_id), ("book", book), ("market", market), ("selection", selection)):
            actual = str(quote.get(field) or "")
            if field == "market":
                actual = actual.upper()
            if actual != expected:
                reasons.append(f"{label.upper()}_{field.upper()}_MISMATCH")
        if quote.get("threshold") != threshold:
            reasons.append(f"{label.upper()}_THRESHOLD_MISMATCH")
        if not _price(quote.get("price")):
            reasons.append(f"{label.upper()}_PRICE_INVALID")
        for flag in _FORBIDDEN_PROVENANCE:
            if quote.get(flag) is not False:
                reasons.append(f"{label.upper()}_{flag.upper()}_FORBIDDEN")
        try:
            quote_at = _time(quote.get("provider_quote_at_utc"), f"{label.upper()}_PROVIDER_QUOTE")
            captured_at = _time(quote.get("captured_at_utc"), f"{label.upper()}_CAPTURE")
            if quote_at > captured_at:
                reasons.append(f"{label.upper()}_QUOTE_AFTER_CAPTURE")
            if kickoff is not None and (quote_at >= kickoff or captured_at >= kickoff):
                reasons.append(f"{label.upper()}_NOT_PREGAME")
            quote_times[label] = (quote_at, captured_at)
        except ValueError as exc:
            reasons.append(str(exc))
            quote_times[label] = None

        declared_sha = str(quote.get("raw_sha256") or "").lower()
        if not _sha256(declared_sha):
            reasons.append(f"{label.upper()}_RAW_SHA256_INVALID")
        raw_path = _safe_path(root, quote.get("raw_relative_path"))
        if raw_path is None:
            reasons.append(f"{label.upper()}_RAW_PATH_INVALID")
        elif not raw_path.is_file():
            reasons.append(f"{label.upper()}_RAW_MISSING")
        else:
            try:
                actual_sha = sha256(raw_path.read_bytes()).hexdigest()
            except OSError:
                reasons.append(f"{label.upper()}_RAW_READ_FAILED")
            else:
                if actual_sha != declared_sha:
                    reasons.append(f"{label.upper()}_RAW_SHA256_MISMATCH")

    decision_times = quote_times.get("decision")
    close_times = quote_times.get("close")
    if decision_times and close_times:
        decision_quote, decision_capture = decision_times
        close_quote, close_capture = close_times
        if not (decision_quote < close_quote):
            reasons.append("DECISION_QUOTE_NOT_BEFORE_CLOSE")
        if not (decision_capture < close_capture):
            reasons.append("DECISION_CAPTURE_NOT_BEFORE_CLOSE")

    valid = not reasons
    blockers = [] if valid else ["PAIRED_MARKET_EVIDENCE_INVALID"]
    blockers.extend(("MODEL_P_REQUIRED_SEPARATELY", "PROMOTION_EVIDENCE_NOT_ESTABLISHED"))
    return {
        "contract": SCHEMA,
        "pair_sha256": sha256(raw).hexdigest(),
        "paired_market_evidence_present": valid,
        "truth_gate_ready": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "eligibility_changed": False,
        "official_status_granted": False,
        "reasons": sorted(set(reasons)),
        "blockers": sorted(set(blockers)),
    }
