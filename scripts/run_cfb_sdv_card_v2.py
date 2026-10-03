#!/usr/bin/env python3
"""Price a manual DK CFB board with the bakeoff-selected PRIOR_CURRENT_BLEND fit.

Works like the MLB card: a quote is a BET when its edge against the
de-vigged price clears the 2% floor; one team-outcome bet per game
(best of moneyline/spread), totals judged separately. No sportsbook API.

Board JSON: a list of
  {"game_id": "<CFBD id>",
   "quotes": [{"market": "MONEYLINE", "side": "HOME"|"AWAY", "american_odds": -150},
              {"market": "SPREAD", "side": "HOME"|"AWAY", "line": -7.5, "american_odds": -110},
              {"market": "TOTAL", "side": "OVER"|"UNDER", "line": 52.5, "american_odds": -110}]}
SPREAD line is the handicap for the quoted side.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from math import erf, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Bakeoff run 37093707442: per-team joint home/away score RMSE.
TEAM_SCORE_RMSE = 12.018
# Margin and total sigma assuming independent home/away residuals.
COMBINED_SIGMA = TEAM_SCORE_RMSE * sqrt(2.0)
EDGE_FLOOR = 0.02  # same floor as the MLB card (#1230)


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
    raise ValueError("CFB_SDV_MARKET_UNSUPPORTED:" + market)


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
            "devig": "PAIRED_PROPORTIONAL" if fair is not None else "UNPAIRED_RAW_IMPLIED",
            "edge": round(edge, 4),
            "bet_status": "BET" if edge >= EDGE_FLOOR else "PASS",
            "reason": "EDGE_CLEARS_FLOOR" if edge >= EDGE_FLOOR else "BELOW_FLOOR",
        })
    # Same-game guard: one team-outcome bet (ML or spread) and one total per game.
    for fam in (("MONEYLINE", "SPREAD"), ("TOTAL",)):
        bets = [r for r in out if r["market"] in fam and r["bet_status"] == "BET"]
        bets.sort(key=lambda r: -r["edge"])
        for r in bets[1:]:
            r["bet_status"], r["reason"] = "PASS", "SAME_GAME_GUARD"
    return out


def build_rows(board: list, season: int, week: int, asof):
    """Price only from the manual board. No CFBD call and no sportsbook API."""
    del season, week, asof
    rows = []
    for row in board:
        if not isinstance(row, dict):
            raise SystemExit("CFB_SDV_BOARD_ROW_INVALID")
        rows.append({
            "game_id": str(row.get("game_id") or ""),
            "home_team": row.get("home"),
            "away_team": row.get("away"),
            "neutral_site": bool(row.get("neutral_site") or False),
            "weather": row.get("weather") or {"game_indoor": False, "temperature": 70.0, "wind_speed": 0.0},
            "quotes": row.get("quotes") or [],
            "home_prior_metrics": row.get("home_prior_metrics"),
            "away_prior_metrics": row.get("away_prior_metrics"),
            "home_current_metrics": row.get("home_current_metrics"),
            "away_current_metrics": row.get("away_current_metrics"),
            "home_mean": row.get("home_mean"),
            "away_mean": row.get("away_mean"),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board-json", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--asof")
    ap.add_argument("--fit", type=Path, default=ROOT / "config/cfb_sdv_prior_current_blend_fit_v1.json")
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_sdv_card.json"))
    args = ap.parse_args()

    from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit, score_selected_game

    board = json.loads(args.board_json)
    if not isinstance(board, list) or not board:
        raise SystemExit("CFB_SDV_BOARD_ARRAY_REQUIRED")
    model = load_selected_sdv_fit(args.fit)
    results = []
    for row in build_rows(board, args.season, args.week, args.asof):
        if row.get("home_mean") is not None and row.get("away_mean") is not None:
            home, away = float(row["home_mean"]), float(row["away_mean"])
        elif row.get("home_prior_metrics") and row.get("away_prior_metrics"):
            home, away = score_selected_game(model, row)
        else:
            results.append({
                "game_id": row["game_id"],
                "matchup": f"{row.get('away_team')} @ {row.get('home_team')}",
                "bet_status": "PASS",
                "reason": "METRICS_NOT_ON_BOARD_NO_API",
            })
            continue
        priced = price_game(row["game_id"], home, away, row.get("quotes") or [])
        for r in priced:
            r["matchup"] = f"{row.get('away_team')} @ {row.get('home_team')}"
        results.extend(priced or [{"game_id": row["game_id"], "bet_status": "PASS", "reason": "NO_QUOTES"}])
    payload = {
        "schema": "CFB_SDV_CARD_V2",
        "family": "PRIOR_CURRENT_BLEND",
        "bakeoff_run": 37093707442,
        "team_score_rmse": TEAM_SCORE_RMSE,
        "combined_sigma": round(COMBINED_SIGMA, 4),
        "edge_floor": EDGE_FLOOR,
        "sportsbook_api_used": False,
        "cfbd_api_used": False,
        "bets": sum(r.get("bet_status") == "BET" for r in results),
        "results": sorted(results, key=lambda r: -(r.get("edge") or -9)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for r in payload["results"]:
        if "edge" in r:
            print(f"{r['bet_status']:4s} {r['matchup']:45s} {r['market']:9s} {r['side']:5s} {str(r['line'] or ''):6s} "
                  f"{r['american_odds']:+6.0f}  model {r['model_p']:.3f}  mkt {r['market_p']:.3f}  edge {r['edge']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
