#!/usr/bin/env python3
"""Price an NFL phone ticket with frozen Attempt 9. Fail closed."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json

from sports.common.ev_math import devig
from sportsedge.nfl_attempt9_live_forecast import (
    load_model_p,
    load_runtime,
    market_eligibility,
    raw_forecasts,
    recency_features,
)
from sportsedge.nfl_run_it_scoring import qualification_role_score
from sportsedge.sports.nfl.attempt9_model_p import model_probability
from sportsedge.truth_gate import american_to_decimal


# Markets whose card-legal model has beaten breakeven (52.4% at -110) in an
# out-of-sample backtest vs closing lines. Anything else is shown as a
# no-edge LEAN for tracking only and never counted as a pick/bet.
BET_PROVEN_MARKETS: frozenset[str] = frozenset()
LEAN_REASON = {
    "total": "LEAN_ONLY:NO_PROVEN_EDGE (Attempt 9 totals 49.7% OOS 2018,2020-25 vs close)",
}
DEFAULT_LEAN_REASON = "LEAN_ONLY:NO_PROVEN_EDGE (market not backtest-proven)"


def _ev(estimate_p: float, price: int) -> float:
    dec = american_to_decimal(price)
    return estimate_p * dec - 1.0


def _history_rows(raw: object) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("games"), list):
        return raw["games"]
    return []



def _board_rows_from_games(games: list) -> list[dict]:
    """Expand phone markets into both offered sides. Does not invent a missing price."""
    rows = []
    prop_alias = {"anytime_tds": "anytime_td", "anytime_td": "anytime_td"}
    for game in games:
        game_id = f"{game.get('away')}@{game.get('home')}"
        for raw in game.get("markets") or []:
            market = str(raw.get("market") or "").strip()
            if not market:
                continue
            surface = prop_alias.get(market, market)
            over_price = raw.get("away_or_over_price")
            under_price = raw.get("home_or_under_price")
            if market in {"moneyline", "spread"}:
                sides = (("AWAY", over_price), ("HOME", under_price))
            else:
                sides = (("OVER", over_price), ("UNDER", under_price))
            if market in {"anytime_td", "anytime_tds"}:
                sides = (("YES", over_price), ("NO", under_price))
            for side, price in sides:
                if price in (None, ""):
                    continue
                rows.append({
                    "game_id": game_id,
                    "market": surface,
                    "provider_market": surface,
                    "side": side,
                    "selection": side,
                    "line": raw.get("line"),
                    "american_odds": price,
                    "entity_id": raw.get("player") or raw.get("team"),
                    "team_side": raw.get("team"),
                    "player": raw.get("player"),
                    "reason": "QUOTED_PHONE_SIDE",
                })
    return rows


def attach_nfl_phone_board(payload: dict) -> dict:
    """Attach both sides of every prop, side, and total. Presentation only."""
    from sportsedge.football_full_board import board_from_machine_results, catalog_complete

    board = board_from_machine_results("NFL", _board_rows_from_games(payload.get("games") or []))
    payload["full_board"] = board
    summary = dict(payload.get("summary") or {})
    summary["both_sides"] = board["summary"]["both_sides"]
    summary["side_rows"] = board["summary"]["side_rows"]
    summary["total_rows"] = board["summary"]["total_rows"]
    summary["prop_rows"] = board["summary"]["prop_rows"]
    summary["catalog_complete"] = catalog_complete(board["summary"])
    payload["summary"] = summary
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--history", default="")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    ticket = json.loads(Path(args.input).read_text(encoding="utf-8"))
    history = _history_rows(json.loads(Path(args.history).read_text(encoding="utf-8")) if args.history else [])
    runtime = load_runtime()
    artifact = load_model_p()
    asof = date.fromisoformat(str(ticket.get("slate") or date.today().isoformat()))
    games_out = []
    for game in ticket.get("games") or []:
        feat = recency_features(history, home=str(game["home"]), away=str(game["away"]), asof=asof) if history else {"ok": False, "reason": "NO_MODEL:INSUFFICIENT_PRIOR_GAMES"}
        forecast = raw_forecasts(runtime, feat["vector"]) if feat.get("ok") else None
        markets = []
        picks = []
        leans = []
        for raw in game.get("markets") or []:
            blocked = market_eligibility(raw["market"], raw.get("line"))
            if blocked:
                markets.append({**raw, "no_model": blocked})
                continue
            if not feat.get("ok"):
                markets.append({**raw, "no_model": feat["reason"]})
                continue
            assert forecast is not None
            pred = forecast["margin"] if raw["market"] == "spread" else forecast["total"]
            line = float(raw["line"])
            home_line = -line if raw["market"] == "spread" else line
            home_or_over = model_probability(
                artifact,
                market=raw["market"],
                raw_prediction=pred,
                line=home_line,
                selection="home" if raw["market"] == "spread" else "over",
            )
            away_or_under = model_probability(
                artifact,
                market=raw["market"],
                raw_prediction=pred,
                line=home_line,
                selection="away" if raw["market"] == "spread" else "under",
            )
            no_vig = devig([
                american_to_decimal(raw["away_or_over_price"]),
                american_to_decimal(raw["home_or_under_price"]),
            ])
            candidates = [
                {
                    "selection": game["away"] if raw["market"] == "spread" else "Over",
                    "line": line,
                    "price_american": raw["away_or_over_price"],
                    "estimate_p": float(away_or_under["model_p"] if raw["market"] == "spread" else home_or_over["model_p"]),
                    "market_no_vig_p": float(no_vig[0]),
                },
                {
                    "selection": game["home"] if raw["market"] == "spread" else "Under",
                    "line": -line if raw["market"] == "spread" else line,
                    "price_american": raw["home_or_under_price"],
                    "estimate_p": float(home_or_over["model_p"] if raw["market"] == "spread" else away_or_under["model_p"]),
                    "market_no_vig_p": float(no_vig[1]),
                },
            ]
            qualified = []
            for cand in candidates:
                ev = _ev(cand["estimate_p"], cand["price_american"])
                if ev < 0.02:
                    continue
                cand["ev_per_dollar"] = ev
                cand["edge_probability_points"] = cand["estimate_p"] - cand["market_no_vig_p"]
                cand["score_0_100"] = qualification_role_score({
                    "model_ready": True,
                    "pit_safe": True,
                    "role_stable": True,
                    "usage_supported": False,
                    "matchup_supported": True,
                    "injury_context_ready": False,
                    "shared_simulation_ready": False,
                    "market_binding_ready": True,
                })
                qualified.append(cand)
            pick = max(qualified, key=lambda c: (c["ev_per_dollar"], c["edge_probability_points"])) if qualified else None
            if raw["market"] in BET_PROVEN_MARKETS:
                row = {**raw, "no_model": None, "pick": pick, "lean": None}
                if pick:
                    picks.append(pick)
            else:
                if pick:
                    pick = {**pick, "lean_only": True, "lean_reason": LEAN_REASON.get(raw["market"], DEFAULT_LEAN_REASON)}
                    leans.append(pick)
                row = {**raw, "no_model": None, "pick": None, "lean": pick}
            markets.append(row)
        games_out.append({**game, "markets": markets, "picks": picks, "leans": leans, "features": feat})
    payload = {
        "sport": "NFL",
        "context_bound": False,
        "games": games_out,
        "bet_proven_markets": sorted(BET_PROVEN_MARKETS),
        "empty_reason": None if any(g["picks"] for g in games_out) else (
            "No bets: no NFL market on this card has beaten breakeven out of sample yet. "
            "Leans are tracking-only, not bets."
        ),
        "authority_footer": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }
    payload = attach_nfl_phone_board(payload)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
