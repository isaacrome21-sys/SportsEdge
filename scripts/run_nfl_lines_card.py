#!/usr/bin/env python3
"""Price an NFL phone ticket with frozen Attempt 9. Fail closed."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
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
from sportsedge.sports.nfl.market_residual_research import NFLResidualError, price_game_from_pairs
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


# The frozen Attempt 9 isotonic calibration has singleton tail blocks
# (weight 1, mean 1.0). A raw probability that lands there would print an
# absurd ~100% "model EV". Leans need a calibration block with at least this
# many historical games behind it. Card-side guard only; the artifact is frozen.
MIN_CALIBRATION_BLOCK_WEIGHT = 20
LEAN_BLOCK_THIN = "NO_LEAN:THIN_CALIBRATION"
LEAN_BLOCK_DIRECTION = "NO_LEAN:PROJECTION_DISAGREES"


def _calibration_block_weight(artifact: dict, market: str, raw_p: float) -> int:
    """Weight of the isotonic block apply_isotonic_blocks() picks for raw_p."""
    blocks = list(artifact["markets"][market]["calibration_blocks"])
    for block in blocks:
        if float(raw_p) <= float(block["hi"]):
            return int(block["weight"])
    return int(blocks[-1]["weight"])


# nflverse uses "LA" for the Rams (and old franchise codes for relocated teams),
# while the DK intake emits "LAR". Map history to intake codes so every team
# finds its own games. Codes only; no score or line changes.
HISTORY_TEAM_ALIASES = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS"}


def _normalize_team(code: object) -> object:
    return HISTORY_TEAM_ALIASES.get(str(code), code) if code is not None else code


def _history_rows(raw: object) -> list:
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("games"), list):
        rows = raw["games"]
    else:
        return []
    return [
        {**g, "home": _normalize_team(g.get("home")), "away": _normalize_team(g.get("away"))}
        if isinstance(g, dict) else g
        for g in rows
    ]



QB_PROP_MARKETS = frozenset({"passing_yards", "pass_yards", "pass_attempts", "completions", "pass_tds", "interceptions"})


def _last_start_qb(history: list, team: str, asof: date) -> dict | None:
    """Most recent strictly-prior nflverse game for `team` with a listed starting QB."""
    best = None
    for g in history:
        day = str(g.get("date") or "")[:10]
        if not day or day >= asof.isoformat():
            continue
        if g.get("home") == team:
            qb = g.get("home_qb")
        elif g.get("away") == team:
            qb = g.get("away_qb")
        else:
            continue
        if qb and (best is None or day > best["date"]):
            best = {"qb": str(qb), "date": day}
    return best


def _name_key(name: str) -> str:
    parts = [p for p in str(name).replace(".", " ").split() if p]
    return parts[-1].lower() if parts else ""


def game_context(game: dict, history: list, asof: date, feat: dict, forecast: dict | None) -> dict:
    """Facts behind the card, only from data this run actually retrieved.

    Sources: nflverse games history (scores, listed starting QBs) and the
    pasted DK lines. Injuries/inactives are NOT retrieved, so they are never shown.
    """
    home, away = str(game["home"]), str(game["away"])
    ctx: dict = {"sources": []}
    if history:
        ctx["sources"].append("nflverse games")
    if feat.get("ok") and forecast is not None:
        f = feat["features"]
        ctx["projection"] = {
            "total": round(float(forecast["total"]), 1),
            "home_margin": round(float(forecast["margin"]), 1),
            "home_pf": round(float(f["home_points_for"]), 1),
            "home_pa": round(float(f["home_points_against"]), 1),
            "away_pf": round(float(f["away_points_for"]), 1),
            "away_pa": round(float(f["away_points_against"]), 1),
            "home_games": feat.get("home_prior_games"),
            "away_games": feat.get("away_prior_games"),
        }
    qbs = {}
    for team in (away, home):
        last = _last_start_qb(history, team, asof) if history else None
        if last:
            qbs[team] = last
    if qbs:
        ctx["last_start_qb"] = qbs
    prop_qbs = sorted({
        str(m["player"]) for m in game.get("markets") or []
        if m.get("player") and str(m.get("market")) in QB_PROP_MARKETS
    })
    if prop_qbs:
        ctx["dk_qb_props"] = prop_qbs
        if qbs:
            known = {_name_key(v["qb"]) for v in qbs.values()}
            unmatched = [n for n in prop_qbs if _name_key(n) not in known]
            if unmatched:
                ctx["qb_change_flag"] = unmatched
    return ctx


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
                line = raw.get("line")
                # Phone spread lines are quoted from the away side; the home side is the mirror.
                if market == "spread" and side == "HOME" and line is not None:
                    line = -float(line)
                rows.append({
                    "game_id": game_id,
                    "market": surface,
                    "provider_market": surface,
                    "side": side,
                    "selection": side,
                    "line": line,
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
        # Never publish absolute-model probabilities as actionable NFL edges.
        # The sole game price path is market-anchored, two-sided, fresh and
        # research-only; existing raw score forecasts remain context only.
        markets = []
        picks = []
        leans = []
        for raw in game.get("markets") or []:
            markets.append({**raw,
                            "no_model": "NO_MODEL:RESIDUAL_RESEARCH_ONLY"
                            if raw.get("market") in {"moneyline","spread","total"}
                            else (market_eligibility(raw["market"],raw.get("line"))
                                  or "NO_MODEL:MARKET_NOT_ON_RESIDUAL_CARD"),
                            "pick":None, "lean":None})
        research = None
        residual_error = "NO_MODEL:INSUFFICIENT_PRIOR_GAMES"
        if feat.get("ok") and forecast is not None:
            try:
                research = price_game_from_pairs(
                    raw_margin=forecast["margin"],raw_total=forecast["total"],
                    markets=game.get("markets") or [],
                    observed_at=ticket.get("observed_at"),
                    as_of=datetime.now(timezone.utc),
                    kickoff_at=game.get("commence_time"),
                    model_family="ATTEMPT9_RAW",
                )
                residual_error = None
            except (NFLResidualError, ValueError, TypeError, KeyError) as exc:
                residual_error = "NO_MODEL:RESIDUAL_" + str(exc)[:150]
        context = game_context(game, history, asof, feat, forecast)
        games_out.append({**game, "markets":markets, "picks":picks, "leans":leans,
                          "features":feat, "context":context,
                          "residual_research":research,
                          "residual_status":residual_error or "RESEARCH_ONLY"})
    payload = {
        "sport": "NFL",
        "residual_pricing_enabled": True,
        "context_bound": False,
        "games": games_out,
        "bet_proven_markets": sorted(BET_PROVEN_MARKETS),
        "empty_reason": None if any(g["picks"] for g in games_out) else (
            "No bets: NFL market-anchored residual prices are research only; forward CLV not yet positive."
        ),
        # Machine-only governance tag; the phone card never prints it.
        "authority_footer": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }
    payload = attach_nfl_phone_board(payload)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
