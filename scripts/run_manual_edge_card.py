#!/usr/bin/env python3
"""Emit bets from a manual board that already has model_p and American odds.

Used for NHL and NBA until each sport has a fitted runner. No sportsbook API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True, choices=("NHL", "NBA"))
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/manual_edge_card.json"))
    args = parser.parse_args()
    rows = json.loads(args.board.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise SystemExit("MANUAL_EDGE_BOARD_ARRAY_REQUIRED")
    results = []
    for row in rows:
        odds = float(row["american_odds"])
        model_p = float(row["model_p"])
        fair = _implied(odds)
        edge = model_p - fair
        ev = model_p * ((odds / 100.0) if odds > 0 else (100.0 / abs(odds))) - (1.0 - model_p)
        results.append({
            "sport": args.sport,
            "game_id": row.get("game_id"),
            "market": row.get("market") or "MONEYLINE",
            "side": row.get("side"),
            "american_odds": odds,
            "model_p": model_p,
            "edge": edge,
            "ev_per_dollar": ev,
            "bet_status": "OFFICIAL_BET" if edge > 0 and ev > 0 else "BLOCKED",
            "reason": "EDGE_POSITIVE" if edge > 0 and ev > 0 else "NO_EDGE",
        })
    payload = {
        "schema": "MANUAL_EDGE_CARD_V1",
        "sport": args.sport,
        "sportsbook_api_used": False,
        "results": results,
        "bets": sum(r["bet_status"] == "OFFICIAL_BET" for r in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sport": args.sport, "bets": payload["bets"], "rows": len(results)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
