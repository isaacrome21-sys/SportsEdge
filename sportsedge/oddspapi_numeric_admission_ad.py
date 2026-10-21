"""OddsPapi numeric admission A/D *offline* diagnostic, never admission.

Purpose: compute bounded comparisons against independently *claimed* DK
samples and claimed actual-first-play anchors, preserving every miss in the
denominator. No input flag can certify either source. Check B (SBR archive
thresholds) is deliberately unimplemented until a separately identified,
owner-frozen numeric contract is located. Every output is NOT_ADMITTED.

This module does not make network calls, read credentials, update the held
#2436 parser, alter frozen source contracts, or promote a market.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
import re
from typing import Any, Mapping

VERSION = "ODDSPAPI_NUMERIC_ADMISSION_AD_DRYRUN_V1"
A_MAX_TIME_DIFF_SECONDS = 30 * 60
A_MAX_AMERICAN_PRICE_DIFF = 10
A_MIN_MATCH_RATE = Decimal("0.95")
D_REQUIRED_PRESTART_SHARE = Decimal("1.00")
_SHA = re.compile(r"^[0-9a-fA-F]{64}$")
_ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_SIDES = {"HOME", "AWAY", "OVER", "UNDER", "YES", "NO"}
_ENVELOPE_KEYS = {"version", "dk_cohort_manifest_sha256", "dk_samples",
                  "close_candidates"}
_PAIR_KEYS = {"sample_id", "dk", "oddspapi"}
_QUOTE_KEYS = {"canonical_event_id", "market_id", "bookmaker", "side",
               "line", "captured_at_utc", "american_price", "source_sha256"}
_PAPI_KEYS = (_QUOTE_KEYS - {"american_price"}) | {"decimal_price"}
_CLOSE_KEYS = {"canonical_event_id", "market_id", "bookmaker",
               "provider_created_at_utc", "candidate_sha256",
               "actual_first_play"}


class NumericAdmissionRefusal(ValueError):
    """Stable refusal code; never include raw evidence or credentials."""


def _stamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise NumericAdmissionRefusal(name + "_UTC_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NumericAdmissionRefusal(name + "_UTC_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NumericAdmissionRefusal(name + "_UTC_OFFSET_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise NumericAdmissionRefusal(name + "_SHA256_REQUIRED")
    return value.lower()


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise NumericAdmissionRefusal(name + "_ID_REQUIRED")
    return value


def _num(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise NumericAdmissionRefusal(name + "_NUMERIC_REQUIRED")
    try:
        num = Decimal(str(value))
    except InvalidOperation as exc:
        raise NumericAdmissionRefusal(name + "_NUMERIC_INVALID") from exc
    if not num.is_finite():
        raise NumericAdmissionRefusal(name + "_NONFINITE")
    return num


def _american_from_decimal(decimal_price: Decimal) -> int:
    if decimal_price <= 1 or decimal_price > 100000:
        raise NumericAdmissionRefusal("ODDSPAPI_DECIMAL_PRICE_INVALID")
    amer = ((decimal_price - 1) * 100 if decimal_price >= 2
            else -100 / (decimal_price - 1))
    return int(amer.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _validate_quote(quote: Any, *, papi: bool) -> dict:
    keys = _PAPI_KEYS if papi else _QUOTE_KEYS
    if not isinstance(quote, Mapping) or set(quote) != keys:
        raise NumericAdmissionRefusal("QUOTE_SCHEMA_INVALID")
    event = _id(quote.get("canonical_event_id"), "EVENT")
    market = _id(quote.get("market_id"), "MARKET")
    side = quote.get("side")
    if not isinstance(side, str) or side not in _SIDES:
        raise NumericAdmissionRefusal("QUOTE_SIDE_UNKNOWN")
    book = quote.get("bookmaker")
    if book != "draftkings":
        raise NumericAdmissionRefusal("A_REQUIRES_EXACT_DK_BOOK")
    line = quote.get("line")
    # A moneyline has null line. All other numerical lines must be exact,
    # never interpolated or rounded to the nearest offered threshold.
    numeric_line = None if line is None else _num(line, "LINE")
    stamp = _stamp(quote.get("captured_at_utc"), "QUOTE")
    source_hash = _sha(quote.get("source_sha256"), "SOURCE")
    if papi:
        decimal_price = _num(quote.get("decimal_price"), "ODDSPAPI_PRICE")
        price = _american_from_decimal(decimal_price)
    else:
        price = quote.get("american_price")
        if type(price) is not int or (-100 < price < 100) or (
                price < -100000 or price > 100000):
            raise NumericAdmissionRefusal("DK_AMERICAN_PRICE_INVALID")
    return {
        "event": event, "market": market, "side": side,
        "line": numeric_line, "bookmaker": book, "time": stamp,
        "american": price, "source_sha256": source_hash,
    }


def _assess_a(sample: Mapping[str, Any]) -> dict:
    sample_id = _id(sample.get("sample_id"), "SAMPLE")
    if set(sample) != _PAIR_KEYS:
        raise NumericAdmissionRefusal("A_PAIR_SCHEMA_INVALID")
    if sample.get("dk") is None or sample.get("oddspapi") is None:
        return {"sample_id": sample_id, "status": "FAIL",
                "reason": "A_UNPAIRED_SAMPLE"}
    dk = _validate_quote(sample["dk"], papi=False)
    papi = _validate_quote(sample["oddspapi"], papi=True)
    if (dk["event"], dk["market"], dk["side"], dk["bookmaker"]) != (
            papi["event"], papi["market"], papi["side"], papi["bookmaker"]):
        reason = "A_FIXTURE_MARKET_SIDE_BOOK_MISMATCH"
    elif dk["line"] != papi["line"]:
        reason = "A_LINE_NOT_EXACT"
    elif abs((dk["time"] - papi["time"]).total_seconds()) > (
            A_MAX_TIME_DIFF_SECONDS):
        reason = "A_QUOTE_OUTSIDE_30_MINUTES"
    elif abs(dk["american"] - papi["american"]) > A_MAX_AMERICAN_PRICE_DIFF:
        reason = "A_AMERICAN_PRICE_DIFFERENCE_GT_10"
    else:
        reason = None
    return {
        "sample_id": sample_id,
        "status": "PASS_NUMERIC_ONLY" if reason is None else "FAIL",
        "reason": reason,
        "time_gap_seconds": int(abs((dk["time"] - papi["time"]).total_seconds())),
        "american_price_difference": abs(dk["american"] - papi["american"]),
        "line_exact": dk["line"] == papi["line"],
    }


def _assess_d(close: Mapping[str, Any]) -> dict:
    if not isinstance(close, Mapping) or set(close) != _CLOSE_KEYS:
        raise NumericAdmissionRefusal("D_CLOSE_SCHEMA_INVALID")
    event = _id(close.get("canonical_event_id"), "D_EVENT")
    _id(close.get("market_id"), "D_MARKET")
    if close.get("bookmaker") != "draftkings":
        raise NumericAdmissionRefusal("D_REQUIRES_EXACT_DK_BOOK")
    receipt = _sha(close.get("candidate_sha256"), "D_CLOSE_RECEIPT")
    created = _stamp(close.get("provider_created_at_utc"), "D_CLOSE")
    anchor = close.get("actual_first_play")
    if not isinstance(anchor, Mapping) or set(anchor) != (
            {"canonical_event_id", "actual_first_play_utc",
             "official_source_sha256"}):
        return {"receipt_sha256": receipt, "status": "FAIL",
                "reason": "D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED"}
    if _id(anchor.get("canonical_event_id"), "D_ACTUAL_EVENT") != event:
        return {"receipt_sha256": receipt, "status": "FAIL",
                "reason": "D_ACTUAL_START_EVENT_MISMATCH"}
    # Provenance fields are not proof of independence; actual start must
    # be authenticated outside this numerical function.
    _sha(anchor.get("official_source_sha256"), "ACTUAL_START_SOURCE")
    first_play = _stamp(anchor.get("actual_first_play_utc"), "ACTUAL_FIRST_PLAY")
    return {
        "receipt_sha256": receipt,
        "status": "PASS_NUMERIC_ONLY" if created < first_play else "FAIL",
        "reason": None if created < first_play else "D_CLOSE_AT_OR_AFTER_FIRST_PLAY",
    }


def evaluate_numeric_admission_dryrun(payload: Mapping[str, Any]) -> dict:
    """A: ±30m exact line ±10 American ≥95%. D: strict prestart 100%.

    No B threshold supplied = NO B evaluation, and NO ADMITTED possible.
    No caller-supplied 'passed' flags, source-attestation boolean or
    threshold overrides are permitted. Input arrays are an unverified sample,
    so claimed A/D numeric pass is a diagnostic, not a source verdict.
    """
    if not isinstance(payload, Mapping) or set(payload) != _ENVELOPE_KEYS or (
            payload.get("version") != VERSION):
        raise NumericAdmissionRefusal("DRYRUN_FIXED_SCHEMA_REQUIRED")
    manifest = _sha(payload.get("dk_cohort_manifest_sha256"), "DK_COHORT")
    samples = payload.get("dk_samples")
    closes = payload.get("close_candidates")
    if not isinstance(samples, list) or not samples:
        raise NumericAdmissionRefusal("A_NONEMPTY_FIXED_COHORT_REQUIRED")
    if not isinstance(closes, list) or not closes:
        raise NumericAdmissionRefusal("D_NONEMPTY_CANDIDATE_COHORT_REQUIRED")
    if not all(isinstance(row, Mapping) for row in samples):
        raise NumericAdmissionRefusal("A_PAIR_SCHEMA_INVALID")
    if not all(isinstance(row, Mapping) for row in closes):
        raise NumericAdmissionRefusal("D_CLOSE_SCHEMA_INVALID")
    a_rows = [_assess_a(row) for row in samples]
    if len({r["sample_id"] for r in a_rows}) != len(a_rows):
        raise NumericAdmissionRefusal("A_DUPLICATE_SAMPLE_ID")
    d_rows = [_assess_d(row) for row in closes]
    if len({r["receipt_sha256"] for r in d_rows}) != len(d_rows):
        raise NumericAdmissionRefusal("D_DUPLICATE_CLOSE_RECEIPT")
    a_n = len(a_rows)
    a_pass = sum(r["status"] == "PASS_NUMERIC_ONLY" for r in a_rows)
    d_n = len(d_rows)
    d_pass = sum(r["status"] == "PASS_NUMERIC_ONLY" for r in d_rows)
    a_fraction = Decimal(a_pass) / Decimal(a_n)
    d_fraction = Decimal(d_pass) / Decimal(d_n)
    return {
        "version": VERSION, "status": "NOT_ADMITTED_NUMERIC_DRYRUN",
        "dk_cohort_manifest_sha256": manifest,
        "source_cohort_independently_authenticated": False,
        "actual_first_play_independently_authenticated": False,
        "SBR_archive_evidence_authenticated": False,
        "check_A": {
            "required_match_rate": "0.95",
            "matching_rule": "same_fixture_book_market_side_exact_line_30min_10c",
            "sample_count": a_n, "passed": a_pass, "failed": a_n-a_pass,
            "observed_match_rate": str(a_fraction),
            "numeric_threshold_met_unverified": a_fraction >= A_MIN_MATCH_RATE,
            "rows": a_rows,
        },
        "check_B": {
            "status": "NOT_EVALUATED_SBR_ARCHIVE_THRESHOLDS_NOT_PINNED",
            "numeric_threshold_met": False,
            "owner_frozen_policy_present": False,
        },
        "check_D": {
            "required_pre_actual_first_play_rate": "1.00",
            "candidate_close_count": d_n,
            "passed": d_pass, "failed": d_n-d_pass,
            "observed_prestart_rate": str(d_fraction),
            "numeric_threshold_met_unverified": d_fraction == D_REQUIRED_PRESTART_SHARE,
            "rows": d_rows,
        },
        "admission": "NOT_ADMITTED",
        "eligible": False, "play_authority": False,
        "certified_close_authority": False,
        "market_test": "NOT_STARTED", "clock_started": False,
        "notes": [
            "Check B numeric thresholds absent from the identified pinned replay contract.",
            "A/D self-reported evidence hashes do not establish provider authenticity or cohort completeness.",
            "No actual provider data was fetched or certified by this code.",
        ],
    }
