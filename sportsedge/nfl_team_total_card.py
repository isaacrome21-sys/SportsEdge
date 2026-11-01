"""Bet-card filter for NFL_TEAM_TOTAL_DIST_V1 forward records.

The frozen runner (freeze PR #2860) picks by |mu - line| >= 2.0 and that
rule is preregistered, so it is NOT changed here; forward evidence rows stay
exactly as priced. This module only decides which picked rows are shown as
bettable plays on the card.

A picked row is a PLAY only if:
  0. EV, mu, Lane A mean, line and price are all finite real numbers
     (NaN/inf/bool/missing -> PASS with BAD_INPUT_<field>), and
  1. EV on the picked side is > 0 (a negative-EV pick is never bet), and
  2. the engine mean is within MAX_LANE_A_DIVERGENCE points of the
     independent Lane A team mean (a larger split means a suspect input,
     e.g. a broken opponent defensive rate), and
  3. EV on the picked side is <= MAX_PLAUSIBLE_EV (larger edges on an NFL
     team total are treated as an input error until reviewed).
Anything else is PASS with a reason code. Plays are ranked by EV, high to low.
"""
from __future__ import annotations

import math
from typing import Iterable

MAX_LANE_A_DIVERGENCE = 5.0
MAX_PLAUSIBLE_EV = 0.35

_SIDE = {"PICKED_OVER": "OVER", "PICKED_UNDER": "UNDER"}


def _finite(v):
    """float(v) if v is a finite real number (not bool), else None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def classify(record: dict) -> dict:
    side = _SIDE.get(record.get("pick"))
    entry = record.get("entry") if isinstance(record.get("entry"), dict) else {}
    out = {"row_id": record.get("row_id"), "team": record.get("team"),
           "side": side, "line": entry.get("line"),
           "price": None, "ev": None, "status": "PASS", "reasons": []}
    if side is None:
        out["reasons"].append("NOT_PICKED")
        return out
    price = _finite(entry.get("over_price" if side == "OVER" else "under_price"))
    line = _finite(entry.get("line"))
    ev = _finite((record.get("ev") or {}).get(side))
    mu = _finite(record.get("mu"))
    lane_a = _finite((record.get("lane_a") or {}).get("team_mean"))
    out["price"], out["ev"] = price, ev
    for name, val in (("EV", ev), ("MU", mu), ("LINE", line), ("PRICE", price)):
        if val is None:
            out["reasons"].append("BAD_INPUT_" + name)
    if price is not None and -100 < price < 100:
        out["reasons"].append("BAD_INPUT_PRICE")
    if lane_a is None:
        out["reasons"].append("LANE_A_MISSING")
    elif mu is not None and abs(mu - lane_a) > MAX_LANE_A_DIVERGENCE:
        out["reasons"].append("LANE_A_DIVERGENCE")
    if ev is not None:
        if ev <= 0:
            out["reasons"].append("NEGATIVE_EV_ON_PICKED_SIDE")
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
