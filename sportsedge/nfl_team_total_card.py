"""Bet-card filter for NFL_TEAM_TOTAL_DIST_V1 forward records.

The frozen runner (freeze PR #2860) picks by |mu - line| >= 2.0 and that
rule is preregistered, so it is NOT changed here; forward evidence rows stay
exactly as priced. This module only decides which picked rows are shown as
bettable plays on the card.

A picked row is a PLAY only if:
  1. EV on the picked side is > 0 (a negative-EV pick is never bet), and
  2. the engine mean is within MAX_LANE_A_DIVERGENCE points of the
     independent Lane A team mean (a larger split means a suspect input,
     e.g. a broken opponent defensive rate), and
  3. EV on the picked side is <= MAX_PLAUSIBLE_EV (larger edges on an NFL
     team total are treated as an input error until reviewed).
Anything else is PASS with a reason code. Plays are ranked by EV, high to low.
"""
from __future__ import annotations

from typing import Iterable

MAX_LANE_A_DIVERGENCE = 5.0
MAX_PLAUSIBLE_EV = 0.35

_SIDE = {"PICKED_OVER": "OVER", "PICKED_UNDER": "UNDER"}


def classify(record: dict) -> dict:
    side = _SIDE.get(record.get("pick"))
    out = {"row_id": record.get("row_id"), "team": record.get("team"),
           "side": side, "line": record.get("entry", {}).get("line"),
           "price": None, "ev": None, "status": "PASS", "reasons": []}
    if side is None:
        out["reasons"].append("NOT_PICKED")
        return out
    entry = record["entry"]
    out["price"] = entry["over_price" if side == "OVER" else "under_price"]
    ev = float(record["ev"][side])
    out["ev"] = ev
    if ev <= 0:
        out["reasons"].append("NEGATIVE_EV_ON_PICKED_SIDE")
    lane_a = (record.get("lane_a") or {}).get("team_mean")
    if lane_a is None:
        out["reasons"].append("LANE_A_MISSING")
    elif abs(float(record["mu"]) - float(lane_a)) > MAX_LANE_A_DIVERGENCE:
        out["reasons"].append("LANE_A_DIVERGENCE")
    if ev > MAX_PLAUSIBLE_EV:
        out["reasons"].append("EV_IMPLAUSIBLE")
    if not out["reasons"]:
        out["status"] = "PLAY"
    return out


def build_card(records: Iterable[dict]) -> list[dict]:
    rows = [classify(r) for r in records]
    picked = [r for r in rows if r["side"] is not None]
    return sorted(picked, key=lambda r: (r["status"] != "PLAY",
                                         -(r["ev"] or 0.0)))


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    recs = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
    for r in build_card(recs):
        print(r["status"], r["team"], r["side"], r["line"], r["price"],
              f"{r['ev']:+.3f}", ",".join(r["reasons"]))
