#!/usr/bin/env python3
"""Price an NFL phone ticket with frozen Attempt 9. Fail closed."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json

from sportsedge.nfl_attempt9_live_forecast import (
    load_model_p,
    load_runtime,
    market_eligibility,
    raw_forecasts,
    recency_features,
)
from sportsedge.sports.nfl.attempt9_model_p import model_probability
from sportsedge.devig import power_devig
from sportsedge.nfl_run_it_scoring import american_from_probability, qualification_role_score
from sportsedge.truth_gate import american_to_decimal


def _ev(estimate_p: float, price: int) -> float:
    dec = american_to_decimal(price)
    return estimate_p * dec - 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--history", default="")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    ticket = json.loads(Path(args.input).read_text(encoding="utf-8"))
    history = json.loads(Path(args.history).read_text(encoding="utf-8")) if args.history else []
    runtime = load_runtime()
    artifact = load_model_p()
    asof = date.fromisoformat(str(ticket.get("slate") or date.today().isoformat()))
    games_out = []
    for game in ticket.get("games") or []:
        feat = recency_features(history, home=str(game["home"]), away=str(game["away"]), asof=asof) if history else {"ok": False, "reason": "NO_MODEL:INSUFFICIENT_PRIOR_GAMES"}
        forecast = raw_forecasts(runtime, feat["vector"]) if feat.get("ok") else None
        markets = []
        picks = []
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
            # Away spread line is pasted as the away handicap; convert to home handicap.
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
            no_vig = power_devig(raw["away_or_over_price"], raw["home_or_under_price"])
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
            row = {**raw, "no_model": None, "pick": pick}
            markets.append(row)
            if pick:
                picks.append(pick)
        games_out.append({**game, "markets": markets, "picks": picks, "features": feat})
    payload = {
        "sport": "NFL",
        "context_bound": False,
        "games": games_out,
        "empty_reason": None if any(g["picks"] for g in games_out) else "Nothing looks strong enough, or every market is NO_MODEL.",
        "authority_footer": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
