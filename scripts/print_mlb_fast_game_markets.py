#!/usr/bin/env python3
"""Print actionable MLB game markets from the already-scored fast card.

Presentation only. Reads card.json produced by render_mlb_myspari_card.py and
does not recompute probabilities, edges, EV, qualification flags, or pricing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

GAME_MARKETS = frozenset({
    "MONEYLINE",
    "RUN_LINE",
    "TOTALS",
    "TEAM_TOTALS",
    "F5_MONEYLINE",
    "F5_RUN_LINE",
    "F5_TOTALS",
    "F5_TEAM_TOTALS",
    "NRFI",
    "YRFI",
})


def _rank(row: dict) -> tuple[int, float]:
    try:
        score = int(row.get("confidence_score") or 0)
    except (TypeError, ValueError):
        score = 0
    try:
        ev = float(row.get("ev_per_dollar"))
    except (TypeError, ValueError):
        ev = -1e9
    return score, ev


def actionable_game_rows(payload: dict) -> list[dict]:
    rows = [
        dict(row)
        for row in (payload.get("rows") or [])
        if isinstance(row, dict)
        and str(row.get("market") or "").upper() in GAME_MARKETS
        and str(row.get("scored_status") or row.get("status") or "").upper() == "ACTIONABLE"
    ]
    rows.sort(key=_rank, reverse=True)
    return rows


def _selection(row: dict) -> str:
    market = str(row.get("market") or "").upper()
    side = str(row.get("side") or "")
    name = str(row.get("entity_name") or "").strip()
    line = row.get("line")
    if line is None or market in {"MONEYLINE", "F5_MONEYLINE", "NRFI", "YRFI"}:
        suffix = ""
    elif market in {"RUN_LINE", "F5_RUN_LINE"}:
        suffix = f" {float(line):+g}"
    else:
        suffix = f" {float(line):g}"
    bits = [x for x in (name, market.replace("_", " ").title(), side.title() + suffix) if x]
    return " ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card-json", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.card_json).read_text(encoding="utf-8"))
    rows = actionable_game_rows(payload)
    print("FAST_MLB_GAME_BETS_BEGIN")
    if not rows:
        print("NO_ACTIONABLE_GAME_MARKETS")
    for row in rows:
        out = {
            "pick": _selection(row),
            "odds": row.get("american_odds"),
            "model_p": row.get("model_p"),
            "edge": row.get("edge"),
            "ev_per_dollar": row.get("ev_per_dollar"),
            "score": row.get("confidence_score"),
            "status": row.get("scored_status") or row.get("status"),
        }
        print(json.dumps(out, sort_keys=True, separators=(",", ":")))
    print("FAST_MLB_GAME_BETS_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
