#!/usr/bin/env python3
"""Price a manual CFB board from the selected PRIOR_CURRENT_BLEND fit.

Input rows must already be dual-snapshot training shape plus quotes.
No sportsbook API. No freeze status change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit, score_selected_game

# Bakeoff run 37093707442 joint RMSE for PRIOR_CURRENT_BLEND.
RESIDUAL_SIGMA = 12.018


def _american_implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _moneyline_p(home: float, away: float) -> float:
    from math import erf, sqrt
    margin = home - away
    z = margin / (RESIDUAL_SIGMA * sqrt(2.0))
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--fit", type=Path, default=ROOT / "config/cfb_sdv_prior_current_blend_fit_v1.json")
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_sdv_card.json"))
    args = parser.parse_args()
    model = load_selected_sdv_fit(args.fit)
    rows = json.loads(args.board.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise SystemExit("CFB_SDV_BOARD_ARRAY_REQUIRED")
    results = []
    for row in rows:
        home, away = score_selected_game(model, row)
        model_p = _moneyline_p(home, away)
        quotes = row.get("quotes") or []
        if not quotes:
            results.append({
                "game_id": row.get("game_id"),
                "home_mean": home,
                "away_mean": away,
                "model_p": model_p,
                "bet_status": "BLOCKED",
                "reason": "NO_QUOTES",
            })
            continue
        for quote in quotes:
            side = str(quote.get("side") or "").upper()
            odds = float(quote["american_odds"])
            p = model_p if side == "HOME" else 1.0 - model_p
            fair = _american_implied(odds)
            edge = p - fair
            results.append({
                "game_id": row.get("game_id"),
                "market": quote.get("market") or "MONEYLINE",
                "side": side,
                "american_odds": odds,
                "home_mean": home,
                "away_mean": away,
                "model_p": p,
                "edge": edge,
                "bet_status": "OFFICIAL_BET" if edge > 0 else "BLOCKED",
                "reason": "EDGE_POSITIVE" if edge > 0 else "NO_EDGE",
            })
    payload = {
        "schema": "CFB_SDV_CARD_V1",
        "family": "PRIOR_CURRENT_BLEND",
        "ridge_alpha": 300.0,
        "residual_sigma": RESIDUAL_SIGMA,
        "sportsbook_api_used": False,
        "results": results,
        "bets": sum(r["bet_status"] == "OFFICIAL_BET" for r in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bets": payload["bets"], "rows": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
