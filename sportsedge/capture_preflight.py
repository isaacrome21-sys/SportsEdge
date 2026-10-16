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


def capture_order(sections: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Stable order: non-critical sections first, candidate-critical last."""
    items = [dict(s) for s in sections]
    return ([s for s in items if not s.get("candidate_critical")]
            + [s for s in items if s.get("candidate_critical")])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _verify(row: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
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
    return captured, None


def preflight(rows: Iterable[Mapping[str, Any]], *, declared_as_of: Any = None,
              failed_refresh_attempts: Iterable[Mapping[str, Any]] = ()) -> dict:
    src = [copy.deepcopy(dict(r)) for r in rows]
    checked = []
    for r in src:
        inst, code = _verify(r)
        checked.append((r, inst, code))
    instants = [i for _, i, c in checked if c is None]
    if not instants:
        raise ValueError("NO_VERIFIED_ROWS")
    final = max(instants)
    if declared_as_of is not None:
        declared = _parse(declared_as_of)
        if declared != final:
            raise ValueError("AS_OF_NOT_FINAL_VERIFICATION_INSTANT")
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
            if not is_fresh(f):
                o["refusal_code"] = f["code"]
        else:
            o["freshness_code"] = None
            o["refusal_code"] = code
        out_rows.append(o)
        if "refusal_code" in o:
            refused.append(o)
    return {
        "as_of_utc": _iso(final),
        "as_of_source": "ACTUAL_FINAL_VERIFICATION_INSTANT",
        "span_seconds": round(span, 3),
        "span_status": span_status,
        "target_span_seconds": TARGET_CAPTURE_SPAN_SECONDS,
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "rows": out_rows,
        "refused": refused,
        "failed_refresh_attempts": [dict(a) for a in failed_refresh_attempts],
        "research_only": True,
    }
