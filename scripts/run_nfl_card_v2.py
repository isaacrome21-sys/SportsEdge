#!/usr/bin/env python3
"""Price a manual DK NFL board from supplied score means.

Does not touch the hashed M2 run machine. A quote is a BET when edge
against the de-vigged price clears 2%. One team bet per game, plus one total.
No sportsbook API.
"""
from __future__ import annotations

import argparse
import json
from math import erf, sqrt
from pathlib import Path

TEAM_SCORE_RMSE = 10.0
COMBINED_SIGMA = TEAM_SCORE_RMSE * sqrt(2.0)
EDGE_FLOOR = 0.02


def phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def implied(odds: float) -> float:
    return abs(odds) / (abs(odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def model_prob(market: str, side: str, line, home: float, away: float) -> float:
    margin, total = home - away, home + away
    if market == "MONEYLINE":
        p_home = phi(margin / COMBINED_SIGMA)
        return p_home if side == "HOME" else 1.0 - p_home
    if market == "SPREAD":
        m = margin if side == "HOME" else -margin
        return phi((m + float(line)) / COMBINED_SIGMA)
    if market == "TOTAL":
        p_over = 1.0 - phi((float(line) - total) / COMBINED_SIGMA)
        return p_over if side == "OVER" else 1.0 - p_over
    raise ValueError("NFL_CARD_MARKET_UNSUPPORTED:" + market)


def pair_key(market: str, side: str, line):
    if market == "MONEYLINE":
        return (market,)
    if market == "SPREAD":
        lv = float(line)
        return (market, lv if side == "HOME" else -lv)
    return (market, float(line))


def price_game(game_id, home: float, away: float, quotes: list) -> list:
    norm = []
    for q in quotes:
        market = str(q.get("market") or "MONEYLINE").upper()
        side = str(q.get("side") or "").upper()
        norm.append((market, side, q.get("line"), float(q["american_odds"])))
    groups = {}
    for market, side, line, odds in norm:
        groups.setdefault(pair_key(market, side, line), []).append(implied(odds))
    out = []
    for market, side, line, odds in norm:
        raw = implied(odds)
        grp = groups[pair_key(market, side, line)]
        fair = raw / sum(grp) if len(grp) == 2 else None
        p = model_prob(market, side, line, home, away)
        edge = p - (fair if fair is not None else raw)
        out.append({
            "game_id": game_id,
            "market": market,
            "side": side,
            "line": line,
            "american_odds": odds,
            "home_mean": round(home, 2),
            "away_mean": round(away, 2),
            "model_p": round(p, 4),
            "market_p": round(fair if fair is not None else raw, 4),
            "edge": round(edge, 4),
            "bet_status": "BET" if edge >= EDGE_FLOOR else "PASS",
            "reason": "EDGE_CLEARS_FLOOR" if edge >= EDGE_FLOOR else "BELOW_FLOOR",
        })
    for fam in (("MONEYLINE", "SPREAD"), ("TOTAL",)):
        bets = [r for r in out if r["market"] in fam and r["bet_status"] == "BET"]
        bets.sort(key=lambda r: -r["edge"])
        for r in bets[1:]:
            r["bet_status"], r["reason"] = "PASS", "SAME_GAME_GUARD"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board-json", required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_it/nfl_card.json"))
    args = parser.parse_args()
    board = json.loads(args.board_json)
    if not isinstance(board, list) or not board:
        raise SystemExit("NFL_CARD_BOARD_ARRAY_REQUIRED")
    results = []
    for row in board:
        results.extend(price_game(row.get("game_id"), float(row["home_mean"]), float(row["away_mean"]), row.get("quotes") or []))
    payload = {
        "schema": "NFL_CARD_V2",
        "sportsbook_api_used": False,
        "edge_floor": EDGE_FLOOR,
        "results": results,
        "bets": sum(r["bet_status"] == "BET" for r in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bets": payload["bets"], "rows": len(results)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
