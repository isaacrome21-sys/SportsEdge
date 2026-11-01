"""Bet-card filter for NFL_TEAM_TOTAL_DIST_V1 forward records.

The frozen runner (freeze PR #2860) picks by |mu - line| >= 2.0 and that
rule is preregistered, so it is NOT changed here; forward evidence rows stay
exactly as priced. This module only decides which picked rows are shown as
plays on this research card. It is not the canonical RUN IT card and does
not replace the shared Lane A card.json pipeline. It does not authenticate
quotes: authentication is upstream (the runner prices only rows from a
DraftKings capture file). This card only refuses rows that do not carry the
runner's provenance fields or whose quote was stale when priced.

A picked row is a PLAY only if:
  0. the record, entry, ev and lane_a containers are dicts, and EV, mu,
     Lane A mean, line and price are finite real numbers
     (NaN/inf/huge/bool/missing/wrong type -> PASS with BAD_INPUT_<field>), and
  1. the row carries the forward runner's provenance: schema
     NFL_TEAM_TOTAL_FORWARD_ROW_V1, engine_id NFL_TEAM_TOTAL_DIST_V1, label
     PROSPECTIVE (else PROVENANCE_MISSING), and
  2. the picked side has a timezone-aware capture time, the row has a
     timezone-aware priced_at and kickoff, capture <= priced_at <= kickoff,
     and the quote was at most MAX_QUOTE_AGE_S old when priced
     (CAPTURED_AT_MISSING / PRICED_AT_MISSING / KICKOFF_MISSING /
     CAPTURED_AFTER_KICKOFF / PRICED_AFTER_KICKOFF / PRICED_BEFORE_CAPTURE /
     QUOTE_STALE), and
  3. EV on the picked side is >= MIN_EV (+3%, the card headline floor), and
  4. the price is not shorter than PRICE_CAP (-165, the straight-bet cap), and
  5. the engine mean is within MAX_LANE_A_DIVERGENCE points of the
     independent Lane A team mean (a larger split means a suspect input), and
  6. EV on the picked side is <= MAX_PLAUSIBLE_EV (larger edges on an NFL
     team total are treated as an input error until reviewed).
Anything else is PASS with a reason code. Plays are ranked by EV, high to low.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

MIN_EV = 0.03
PRICE_CAP = -165
MAX_LANE_A_DIVERGENCE = 5.0
MAX_PLAUSIBLE_EV = 0.35
MAX_QUOTE_AGE_S = 1800  # owner ruling 2026-10-25: card quote-age limit 30 min

SCHEMA = "NFL_TEAM_TOTAL_FORWARD_ROW_V1"
ENGINE_ID = "NFL_TEAM_TOTAL_DIST_V1"
LABEL = "PROSPECTIVE"

_SIDE = {"PICKED_OVER": "OVER", "PICKED_UNDER": "UNDER"}


def _finite(v):
    """float(v) if v is a finite real number (not bool), else None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _dict(v):
    return v if isinstance(v, dict) else {}


def _ts(v):
    """Timezone-aware datetime from an ISO string, else None."""
    if not isinstance(v, str) or not v:
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def classify(record) -> dict:
    record = _dict(record)
    side = _SIDE.get(record.get("pick")) if isinstance(record.get("pick"), str) else None
    entry = _dict(record.get("entry"))
    out = {"row_id": record.get("row_id"), "team": record.get("team"),
           "side": side, "line": entry.get("line"),
           "price": None, "ev": None, "status": "PASS", "reasons": []}
    if side is None:
        out["reasons"].append("NOT_PICKED")
        return out
    key = "over" if side == "OVER" else "under"
    price = _finite(entry.get(key + "_price"))
    line = _finite(entry.get("line"))
    ev = _finite(_dict(record.get("ev")).get(side))
    mu = _finite(record.get("mu"))
    lane_a = _finite(_dict(record.get("lane_a")).get("team_mean"))
    out["price"], out["ev"] = price, ev
    for name, val in (("EV", ev), ("MU", mu), ("LINE", line), ("PRICE", price)):
        if val is None:
            out["reasons"].append("BAD_INPUT_" + name)
    if price is not None:
        if -100 < price < 100:
            out["reasons"].append("BAD_INPUT_PRICE")
        elif price < PRICE_CAP:
            out["reasons"].append("PRICE_BEYOND_CAP")
    if (record.get("schema") != SCHEMA or record.get("engine_id") != ENGINE_ID
            or record.get("label") != LABEL):
        out["reasons"].append("PROVENANCE_MISSING")
    captured = _ts(entry.get(key + "_captured_at"))
    priced = _ts(record.get("priced_at"))
    kickoff = _ts(record.get("kickoff"))
    if captured is None:
        out["reasons"].append("CAPTURED_AT_MISSING")
    if priced is None:
        out["reasons"].append("PRICED_AT_MISSING")
    if kickoff is None:
        out["reasons"].append("KICKOFF_MISSING")
    if captured is not None and kickoff is not None and captured > kickoff:
        out["reasons"].append("CAPTURED_AFTER_KICKOFF")
    if priced is not None and kickoff is not None and priced > kickoff:
        out["reasons"].append("PRICED_AFTER_KICKOFF")
    if captured is not None and priced is not None:
        age = (priced - captured).total_seconds()
        if age < 0:
            out["reasons"].append("PRICED_BEFORE_CAPTURE")
        elif age > MAX_QUOTE_AGE_S:
            out["reasons"].append("QUOTE_STALE")
    if lane_a is None:
        out["reasons"].append("LANE_A_MISSING")
    elif mu is not None and abs(mu - lane_a) > MAX_LANE_A_DIVERGENCE:
        out["reasons"].append("LANE_A_DIVERGENCE")
    if ev is not None:
        if ev <= 0:
            out["reasons"].append("NEGATIVE_EV_ON_PICKED_SIDE")
        elif ev < MIN_EV:
            out["reasons"].append("EV_BELOW_FLOOR")
        if ev > MAX_PLAUSIBLE_EV:
            out["reasons"].append("EV_IMPLAUSIBLE")
    if not out["reasons"]:
        out["status"] = "PLAY"
    return out


def build_card(records: Iterable[dict]) -> list[dict]:
    rows = [classify(r) for r in records]
    picked = [r for r in rows if r["side"] is not None]
    return sorted(picked, key=lambda r: (r["status"] != "PLAY",
                                         -(r["ev"] if r["ev"] is not None else 0.0)))


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    recs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
    for r in build_card(recs):
        ev = "nan" if r["ev"] is None else f"{r['ev']:+.3f}"
        print(r["status"], r["team"], r["side"], r["line"], r["price"], ev, ",".join(r["reasons"]))
