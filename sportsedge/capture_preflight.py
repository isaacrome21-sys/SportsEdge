"""#2359 A: capture-span preflight. Research only; the 180s bound is UNCHANGED.

This module never rescues a stale quote. It:
* orders capture sections so candidate-critical ones are read last;
* requires a genuine final re-read record for every stamped quote (the
  record's instant must equal the immutable ``quote_captured_at`` and name
  the same row) -- no inferred, redated or reused timestamps;
* anchors the operative as-of to the actual final verification instant;
* refuses every row older than 180s against that as-of (a 217s capture
  still refuses its 197s rows; reordering cannot change recorded instants);
* reports the first-to-last span against a 150s target / 30s margin.
"""
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .quote_freshness import (MAX_QUOTE_AGE_SECONDS, QUOTE_INVALID, _parse,
                              check_quote_freshness, is_fresh)

TARGET_CAPTURE_SPAN_SECONDS = 150
SAFETY_MARGIN_SECONDS = 30
assert TARGET_CAPTURE_SPAN_SECONDS + SAFETY_MARGIN_SECONDS == MAX_QUOTE_AGE_SECONDS

SPAN_WITHIN_TARGET = "CAPTURE_SPAN_WITHIN_150S_TARGET"
SPAN_OVER_TARGET = "CAPTURE_SPAN_OVER_150S_TARGET_INSIDE_180S"
SPAN_OVER_BOUND = "CAPTURE_SPAN_OVER_180S_STALE_ROWS_REFUSED"

REFUSE_NO_FINAL_VERIFICATION = "REFRESH_REQUIRED_NO_GENUINE_FINAL_VERIFICATION"
REFUSE_VERIFICATION_TIMESTAMP_MISMATCH = "REFRESH_REQUIRED_VERIFICATION_TIMESTAMP_MISMATCH"
REFUSE_VERIFICATION_ROW_MISMATCH = "REFRESH_REQUIRED_VERIFICATION_ROW_MISMATCH"
QUOTE_STALE_AT_EVALUATION = "QUOTE_STALE_OVER_180S_AT_EVALUATION_INSTANT"
REFUSE_CAPTURE_RECEIPT_UNPROVEN = "REFRESH_REQUIRED_CAPTURE_RECEIPT_UNPROVEN"
REFUSE_CAPTURE_RECEIPT_MISMATCH = "REFRESH_REQUIRED_CAPTURE_RECEIPT_MISMATCH"

# A self-declared re-read is OPERATOR_DECLARED_FINAL_REREAD and is never proof.
# Only a receipt from a store whose manifest SHA-256 is pinned out of band,
# whose own bytes hash-match the manifest, and whose raw sportsbook read bytes
# hash-match and contain the offer, upgrades a quote to PINNED_CAPTURE_RECEIPT.
PROOF_OPERATOR_DECLARED = "OPERATOR_DECLARED_FINAL_REREAD"
PROOF_PINNED_CAPTURE_RECEIPT = "PINNED_CAPTURE_RECEIPT"
RECEIPT_MANIFEST_PIN_MISMATCH = "CAPTURE_RECEIPT_MANIFEST_PIN_MISMATCH"
RECEIPT_HASH_MISMATCH = "CAPTURE_RECEIPT_HASH_MISMATCH"
RECEIPT_RAW_HASH_MISMATCH = "CAPTURE_RECEIPT_RAW_READ_HASH_MISMATCH"
RECEIPT_OFFER_NOT_IN_RAW_READ = "CAPTURE_RECEIPT_OFFER_NOT_IN_RAW_READ"
RECEIPT_PATH_INVALID = "CAPTURE_RECEIPT_PATH_INVALID"
RECEIPT_MALFORMED = "CAPTURE_RECEIPT_MALFORMED"
RECEIPT_RAW_BINDING_MISMATCH = "CAPTURE_RECEIPT_RAW_READ_ID_OR_TIME_MISMATCH"
RECEIPT_RAW_REUSED = "CAPTURE_RECEIPT_RAW_READ_SHARED_ACROSS_RECEIPTS"
RECEIPT_OFFER_FIELDS = ("game_id", "book", "market", "selection", "period", "line", "player")


def normalize_game_id(value: Any) -> str:
    """Canonical game key: whitespace removed, upper-cased ('nyy @ bos' == 'NYY@BOS')."""
    import re
    return re.sub(r"\s+", "", str(value if value is not None else "")).upper()


def _sha256(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _safe_path(root, rel):
    from pathlib import Path
    root = Path(root).resolve()
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        raise ValueError(RECEIPT_PATH_INVALID)
    p = (root / rel).resolve()
    if root not in p.parents:
        raise ValueError(RECEIPT_PATH_INVALID)
    return p


def load_capture_receipts(root, *, manifest_sha256: str) -> dict:
    """Load a pinned capture-receipt store; any break in the chain raises.

    Trust boundary: receipts are only as trustworthy as whoever wrote the
    manifest. The out-of-band pin proves the store was not altered after the
    writer published it; it does not prove the writer read the sportsbook
    honestly. The raw bytes must carry their own read_id and capture time,
    which must equal the receipt's, and one raw read can back only one
    receipt (no re-wrapping an old read as a new capture)."""
    import json
    from pathlib import Path
    mb = (Path(root) / "manifest.json").read_bytes()
    if not isinstance(manifest_sha256, str) or _sha256(mb) != manifest_sha256.lower():
        raise ValueError(RECEIPT_MANIFEST_PIN_MISMATCH)
    manifest = json.loads(mb)
    out = {}
    raw_seen: set[str] = set()
    for e in manifest.get("receipts") or []:
        rb = _safe_path(root, e.get("path")).read_bytes()
        if _sha256(rb) != e.get("sha256"):
            raise ValueError(RECEIPT_HASH_MISMATCH)
        rc = json.loads(rb)
        if rc.get("receipt_id") != e.get("receipt_id") or not rc.get("read_id"):
            raise ValueError(RECEIPT_MALFORMED)
        raw = _safe_path(root, rc.get("raw_path")).read_bytes()
        if _sha256(raw) != rc.get("raw_sha256"):
            raise ValueError(RECEIPT_RAW_HASH_MISMATCH)
        if rc["raw_sha256"] in raw_seen:
            raise ValueError(RECEIPT_RAW_REUSED)
        raw_seen.add(rc["raw_sha256"])
        try:
            raw_doc = json.loads(raw)
        except ValueError:
            raw_doc = None
        if not isinstance(raw_doc, dict):
            raise ValueError(RECEIPT_OFFER_NOT_IN_RAW_READ)
        try:
            raw_time = _parse(raw_doc.get("captured_at"))
            rc_time = _parse(rc.get("captured_at"))
        except ValueError:
            raw_time = rc_time = None
        if str(raw_doc.get("read_id")) != str(rc["read_id"]) or raw_time is None \
                or raw_time != rc_time:
            raise ValueError(RECEIPT_RAW_BINDING_MISMATCH)
        offer = {k: rc.get(k) for k in RECEIPT_OFFER_FIELDS}
        offer["price"] = rc.get("price")
        offers = raw_doc.get("offers") or []
        if not any(isinstance(o, dict) and all(o.get(k) == v for k, v in offer.items())
                   for o in offers):
            raise ValueError(RECEIPT_OFFER_NOT_IN_RAW_READ)
        if str(rc["read_id"]) in out:
            raise ValueError(RECEIPT_MALFORMED + ":DUPLICATE_READ_ID")
        out[str(rc["read_id"])] = rc
    return out


def capture_order(sections: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Stable order: non-critical sections first, candidate-critical last."""
    items = [dict(s) for s in sections]
    return ([s for s in items if not s.get("candidate_critical")]
            + [s for s in items if s.get("candidate_critical")])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _verify(row: Mapping[str, Any], receipts: Mapping[str, Any] | None = None
            ) -> tuple[datetime | None, str | None]:
    """Return (verified instant, refusal code)."""
    try:
        captured = _parse(row.get("quote_captured_at"))
    except ValueError as exc:
        return None, str(exc) or QUOTE_INVALID
    if captured is None:
        return None, REFUSE_NO_FINAL_VERIFICATION
    ver = row.get("verification")
    if not isinstance(ver, Mapping) or ver.get("reread") is not True \
            or not str(ver.get("read_id") or "").strip():
        return None, REFUSE_NO_FINAL_VERIFICATION
    if str(ver.get("row_id")) != str(row.get("row_id")):
        return None, REFUSE_VERIFICATION_ROW_MISMATCH
    try:
        verified = _parse(ver.get("verified_at"))
    except ValueError as exc:
        return None, str(exc) or QUOTE_INVALID
    if verified is None:
        return None, REFUSE_NO_FINAL_VERIFICATION
    if verified != captured:
        return None, REFUSE_VERIFICATION_TIMESTAMP_MISMATCH
    if not receipts:
        return None, REFUSE_CAPTURE_RECEIPT_UNPROVEN
    rc = receipts.get(str(ver.get("read_id")))
    if rc is None:
        return None, REFUSE_CAPTURE_RECEIPT_UNPROVEN
    if row.get("source_read_id") is not None and str(row["source_read_id"]) != str(rc["read_id"]):
        return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    if not ver.get("raw_sha256"):
        return None, REFUSE_CAPTURE_RECEIPT_UNPROVEN
    if str(ver["raw_sha256"]) != str(rc.get("raw_sha256")):
        return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    if normalize_game_id(rc.get("game_id")) != normalize_game_id(row.get("game_id")):
        return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    if any(rc.get(k) != row.get(k) for k in RECEIPT_OFFER_FIELDS if k != "game_id") \
            or rc.get("price") != row.get("price", row.get("odds")):
        return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    try:
        if _parse(rc.get("captured_at")) != captured:
            return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    except ValueError:
        return None, REFUSE_CAPTURE_RECEIPT_MISMATCH
    return captured, None


def preflight(rows: Iterable[Mapping[str, Any]], *, receipts: Mapping[str, Any] | None,
              evaluated_at: Any, declared_as_of: Any = None,
              failed_refresh_attempts: Iterable[Mapping[str, Any]] = ()) -> dict:
    src = [copy.deepcopy(dict(r)) for r in rows]
    checked = []
    for r in src:
        inst, code = _verify(r, receipts)
        checked.append((r, inst, code))
    instants = [i for _, i, c in checked if c is None]
    if not instants:
        raise ValueError("NO_VERIFIED_ROWS")
    final = max(instants)
    if declared_as_of is not None:
        declared = _parse(declared_as_of)
        if declared != final:
            raise ValueError("AS_OF_NOT_FINAL_VERIFICATION_INSTANT")
    evaluated = _parse(evaluated_at)
    if evaluated is None:
        raise ValueError("EVALUATION_INSTANT_REQUIRED")
    if evaluated < final:
        raise ValueError("EVALUATED_BEFORE_FINAL_READ")
    span = (final - min(instants)).total_seconds()
    if span > MAX_QUOTE_AGE_SECONDS:
        span_status = SPAN_OVER_BOUND
    elif span > TARGET_CAPTURE_SPAN_SECONDS:
        span_status = SPAN_OVER_TARGET
    else:
        span_status = SPAN_WITHIN_TARGET
    out_rows, refused = [], []
    for r, inst, code in checked:
        o = dict(r)
        if code is None:
            f = check_quote_freshness(r["quote_captured_at"], now=final)
            o["freshness_code"] = f["code"]
            o["quote_age_seconds"] = f["age_seconds"]
            fe = check_quote_freshness(r["quote_captured_at"], now=evaluated)
            o["quote_age_at_evaluation_seconds"] = fe["age_seconds"]
            if not is_fresh(f):
                o["refusal_code"] = f["code"]
            elif not is_fresh(fe):
                o["refusal_code"] = QUOTE_STALE_AT_EVALUATION
        else:
            o["freshness_code"] = None
            o["refusal_code"] = code
        out_rows.append(o)
        if "refusal_code" in o:
            refused.append(o)
    return {
        "as_of_utc": _iso(final),
        "as_of_source": "ACTUAL_FINAL_VERIFICATION_INSTANT",
        "evaluated_at_utc": _iso(evaluated),
        "span_seconds": round(span, 3),
        "span_status": span_status,
        "target_span_seconds": TARGET_CAPTURE_SPAN_SECONDS,
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "rows": out_rows,
        "refused": refused,
        "failed_refresh_attempts": [dict(a) for a in failed_refresh_attempts],
        "proof_level": PROOF_PINNED_CAPTURE_RECEIPT,
        "research_only": True,
    }
