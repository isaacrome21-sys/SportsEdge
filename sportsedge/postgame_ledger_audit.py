"""Read-only research audit of supplied postgame rows; never authorizes wagers.

The input is an *untrusted* export. Even a row with a complete quote trail is
only READY_FOR_INDEPENDENT_REVIEW, not a verified pick, CLV, or freeze verdict.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Iterable, Mapping, Any

SETTLED = frozenset({"WIN", "LOSS", "PUSH", "VOID"})
SPORTS = frozenset({"MLB", "NFL", "CFB", "NBA", "NHL", "CBB"})
REQUIRED = ("sport", "event_id", "selection_id", "market", "model_version",
            "captured_at", "event_start", "status", "american_odds", "stake")


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp malformed") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp timezone missing")
    return stamp


def _american(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid American price")
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid American price") from exc
    if not price.is_finite() or price != price.to_integral_value() or abs(price) < 100:
        raise ValueError("invalid American price")
    return price


def _stake(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid stake")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid stake") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("invalid stake")
    return amount


def _profit(status: str, price: Decimal, stake: Decimal) -> Decimal:
    if status == "WIN":
        return stake * (price / 100 if price > 0 else 100 / -price)
    if status == "LOSS":
        return -stake
    return Decimal(0)


def _quote_evidence(row: Mapping[str, Any], entry: datetime, start: datetime,
                    entry_price: Decimal) -> tuple[str, str]:
    """Assess supplied quote metadata, without treating it as authenticated proof."""
    # Legal exclusion outranks missing/slow/invalid quote metadata.
    if row.get("illinois_college") is True and row["sport"] in {"CFB", "CBB"}:
        return "REFUSED", "ILLINOIS_COLLEGE_EXCLUDED"
    if str(row.get("sportsbook", "")).upper() not in {"DK", "DRAFTKINGS"}:
        return "RESEARCH", "DK_SOURCE_NOT_ATTESTED"
    if isinstance(row.get("capture_span_seconds"), bool):
        return "REFUSED", "CAPTURE_SPAN_OUT_OF_RANGE"
    try:
        span = Decimal(str(row["capture_span_seconds"]))
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return "RESEARCH", "CAPTURE_SPAN_MISSING_OR_INVALID"
    if not span.is_finite() or span < 0 or span > 300:
        return "REFUSED", "CAPTURE_SPAN_OUT_OF_RANGE"
    if span > 150:
        return "RESEARCH", "CAPTURE_SPAN_150_TO_300_RESEARCH"
    if entry_price < -165 and str(row.get("wager_type", "STRAIGHT")).upper() == "STRAIGHT":
        return "RESEARCH", "STRAIGHT_PRICE_BELOW_MINUS_165_CAP"
    close_keys = ("close_captured_at", "close_american_odds", "close_opposite_american_odds",
                  "entry_opposite_american_odds")
    if any(row.get(k) in (None, "") for k in close_keys):
        return "RESEARCH", "PAIRED_ENTRY_OR_CLOSE_MISSING"
    try:
        close = _instant(row["close_captured_at"])
        _american(row["close_american_odds"])
        _american(row["close_opposite_american_odds"])
        _american(row["entry_opposite_american_odds"])
    except (ValueError, TypeError):
        return "REFUSED", "CLOSE_PAIR_OR_TIME_INVALID"
    if not entry < close < start:
        return "REFUSED", "CLOSE_NOT_SEPARATE_LATER_PREGAME"
    if str(row.get("close_sportsbook", "")).upper() not in {"DK", "DRAFTKINGS"}:
        return "RESEARCH", "DK_CLOSE_SOURCE_NOT_ATTESTED"
    return "READY_FOR_INDEPENDENT_REVIEW", "SOURCE_AUTHENTICATION_AND_FREEZE_STILL_REQUIRED"


def audit(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reconcile only accepted settlements; never mark any market VERIFIED."""
    findings: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    counts: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    units = Decimal(0)
    for index, row in enumerate(rows):
        missing = [k for k in REQUIRED if row.get(k) in (None, "")]
        if missing:
            findings.append({"row": index, "code": "MISSING_FIELDS", "fields": missing})
            continue
        if not isinstance(row["sport"], str) or row["sport"] not in SPORTS:
            findings.append({"row": index, "code": "UNKNOWN_SPORT"})
            continue
        # Malformed unhashable identities must not abort the entire audit.
        identity_fields = ("event_id", "market", "selection_id", "model_version")
        if any(not isinstance(row[k], (str, int)) or isinstance(row[k], bool)
               for k in identity_fields) or not isinstance(row.get("line"), (int, float, str, type(None))) or (
                   isinstance(row.get("line"), float) and not isfinite(row["line"])):
            findings.append({"row": index, "code": "INVALID_IDENTITY"})
            continue
        # Line differentiates genuine alternate markets at the same event.
        line = None if row.get("line") is None else Decimal(str(row["line"]))
        if line is not None and (not line.is_finite() or abs(line) > 10000):
            findings.append({"row": index, "code": "INVALID_IDENTITY"})
            continue
        key = (row["sport"], row["event_id"], row["market"],
               row["selection_id"], row["model_version"], line)
        if key in seen:
            findings.append({"row": index, "code": "DUPLICATE_SELECTION"})
            continue
        status = str(row["status"]).upper()
        if status not in SETTLED:
            findings.append({"row": index, "code": "UNSETTLED_OR_UNKNOWN"})
            continue
        try:
            entry, start = _instant(row["captured_at"]), _instant(row["event_start"])
            if entry >= start:
                raise ValueError("not pregame")
            price, stake = _american(row["american_odds"]), _stake(row["stake"])
        except (ValueError, TypeError, OverflowError):
            findings.append({"row": index, "code": "INVALID_PRICE_OR_PREGAME_TIME"})
            continue
        seen.add(key)  # Bad/unsettled rows must never poison a later valid row.
        counts[status] += 1
        units += _profit(status, price, stake)
        tier, code = _quote_evidence(row, entry, start, price)
        tiers[tier] += 1
        if tier != "READY_FOR_INDEPENDENT_REVIEW":
            findings.append({"row": index, "code": code})
    return {"settled_rows": sum(counts.values()), "settlement_counts": dict(counts),
            "settlement_profit_units": str(units), "quote_evidence_tiers": dict(tiers),
            "findings": findings, "authority": "RESEARCH_AUDIT_ONLY_NOT_VERIFIED",
            "verified_picks": 0, "play_units_authorized": 0}
