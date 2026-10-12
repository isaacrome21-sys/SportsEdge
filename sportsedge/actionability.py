#!/usr/bin/env python3
"""Actionability breakdown for research cards.

Isaac's day-to-day question is "is there anything actionable?" This module
answers it honestly: every evaluated row is classified into exactly one of

  * ACTIONABLE -- priced AND current-quote candidate: the row passed the
    EV and price gates with quotes verified fresh enough to act on
    (props) or model-side gates passed (games, quote freshness caveat
    below).
  * WATCH -- priced (a probability exists) but NOT a current candidate:
    stale quotes, below the EV floor, price-capped, or lineup/
    participation unverified.
  * BLOCKED -- nothing priced: NO_MODEL_OR_MARKET / BLOCKED_* rows carry
    no probability, so there is no estimate to band or to act on.

The metric only makes the pipeline's yield visible; it changes nothing
about the fail-closed bar. Same honesty principle as the uncertainty
bands: show exactly where each selection landed and why.

Classification rules (declared, from fields already on the rows):

  ACTIONABLE iff status in {RESEARCH_CANDIDATE_NOT_VALIDATED,
      RESEARCH_EDGE} AND a valid priced probability is present.
      - RESEARCH_CANDIDATE_NOT_VALIDATED implies, by bridge construction,
        exactly-paired DK quotes with quote_status == RECENT_CAPTURED_QUOTE,
        EV >= the floor, and price >= the cap.
      - RESEARCH_EDGE (game rows) means model EV >= min_ev and price >=
        -165. CAVEAT: game rows carry no verified quote-capture timestamps
        from chat intake, so "current quotes" for game rows is NOT
        independently verifiable -- see game_quote_freshness_caveat.
  WATCH iff a valid probability exists but the status is not actionable.
  BLOCKED iff no valid probability exists (or the row is not an object).

Fail closed: a row claiming an actionable status WITHOUT a valid
probability is classified BLOCKED, not ACTIONABLE -- data inconsistency
must never produce a phantom candidate.
"""
from __future__ import annotations

from collections import Counter

from .uncertainty import probability_of

SCHEMA = "SPORTSEDGE_ACTIONABILITY_V1"

ACTIONABLE = "ACTIONABLE"
WATCH = "WATCH"
BLOCKED = "BLOCKED"

ACTIONABLE_STATUSES = frozenset({
    "RESEARCH_CANDIDATE_NOT_VALIDATED",
    "RESEARCH_EDGE",
})

GAME_QUOTE_FRESHNESS_CAVEAT = (
    "Game rows (ML/SPREAD/TOTAL) carry no verified quote-capture timestamps "
    "from chat intake: ACTIONABLE for a game row means the model-side EV and "
    "price gates passed, NOT independently verified-current quotes. Prop "
    "rows classified ACTIONABLE have exactly-paired DK quotes verified "
    "RECENT_CAPTURED_QUOTE by the research bridge."
)

_TOP_BLOCKED_REASONS = 10


def classify_row(row):
    """Return (bucket, detail) for one evaluated row.

    Buckets are ACTIONABLE / WATCH / BLOCKED. ``detail`` is a short,
    machine-stable reason string; the row's own status/reason fields
    carry the full story.
    """
    if not isinstance(row, dict):
        return BLOCKED, "NOT_PRICED:ROW_NOT_OBJECT"
    p, _p_reason = probability_of(row)
    status = str(row.get("status") or "")
    if p is not None and status in ACTIONABLE_STATUSES:
        if status == "RESEARCH_CANDIDATE_NOT_VALIDATED":
            return (ACTIONABLE,
                    "PRICED_WITH_FRESH_PAIRED_QUOTES_EV_FLOOR_AND_PRICE_CAP_PASSED")
        return (ACTIONABLE,
                "MODEL_EV_AND_PRICE_GATES_PASSED;"
                "GAME_QUOTE_FRESHNESS_UNVERIFIED_FROM_CHAT_INTAKE")
    if p is not None:
        detail = f"PRICED_BUT_NOT_ACTIONABLE:status={status or 'MISSING_STATUS'}"
        quote_status = row.get("quote_status")
        if quote_status:
            detail += f";quote_status={quote_status}"
        return WATCH, detail
    reason = str(row.get("reason") or "")[:120]
    detail = f"NOT_PRICED:status={status or 'MISSING_STATUS'}"
    if reason:
        detail += f";reason={reason}"
    return BLOCKED, detail


def annotate_actionability(rows):
    """Annotate every evaluated row in place; return the summary block.

    Each row gets top-level ``actionability`` (bucket) and
    ``actionability_detail`` (why). The summary carries counts, percentages
    of total rows, the top BLOCKED reason codes, and the game-quote
    freshness caveat.
    """
    rows = list(rows or [])
    counts = Counter()
    blocked_reasons = Counter()
    blocked_examples = {}
    for row in rows:
        bucket, detail = classify_row(row)
        if isinstance(row, dict):
            row["actionability"] = bucket
            row["actionability_detail"] = detail
        counts[bucket] += 1
        if bucket == BLOCKED and isinstance(row, dict):
            code = str(row.get("status") or "MISSING_STATUS")
            blocked_reasons[code] += 1
            if code not in blocked_examples:
                blocked_examples[code] = detail
    total = len(rows)
    percentages = {
        bucket: round(100.0 * counts.get(bucket, 0) / total, 1) if total else 0.0
        for bucket in (ACTIONABLE, WATCH, BLOCKED)
    }
    top_blocked = [
        {"reason_code": code, "count": blocked_reasons[code],
         "example_detail": blocked_examples[code]}
        for code, _ in blocked_reasons.most_common(_TOP_BLOCKED_REASONS)
    ]
    return {
        "schema": SCHEMA,
        "total_rows": total,
        "counts": {bucket: counts.get(bucket, 0)
                   for bucket in (ACTIONABLE, WATCH, BLOCKED)},
        "percentages": percentages,
        "top_blocked_reasons": top_blocked,
        "game_quote_freshness_caveat": GAME_QUOTE_FRESHNESS_CAVEAT,
        "buckets_defined": {
            ACTIONABLE: ("priced with current quotes; EV and price gates "
                         "passed (props: freshness verified by bridge; "
                         "games: freshness unverified, see caveat)"),
            WATCH: "priced but not a current candidate (stale quotes, below "
                   "EV floor, price-capped, lineup/participation unverified)",
            BLOCKED: "nothing priced; no probability to band or act on",
        },
        "research_only": True,
    }
