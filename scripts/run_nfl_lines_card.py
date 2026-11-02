#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# SUPERSEDED ROUTE (2026-10-12): the ONE canonical RUN IT card path is
# artifacts/run_it_full.py (run_full). This entry point is retained for
# reference/replay only and must not be treated as a canonical card source.
# ---------------------------------------------------------------------------
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
from sportsedge.sports.nfl.market_anchored_residual import (
    ResidualQuoteError, load_frozen_policy, price_game,
)
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
# The frozen Attempt 9 features are built from the team's recent games under
# its LAST LISTED starter. When DK's QB props name a passer who is not either
# team's last starter, the projection describes a different offense than the
# one taking the field; a lean on that game's side/total/ML would be priced
# on the wrong QB. Card-side guard only; the frozen artifact is untouched.
LEAN_BLOCK_QB_CHANGE = "NO_LEAN:QB_CHANGE_UNMODELED"
# Owner requirement (Nov 1, 2026, relay #2447): leans also block when the
# starter CANNOT be verified -- i.e. unless, for BOTH teams, the model's last
# listed starter is corroborated by a DK QB prop on the pasted board. No
# scoring adjustment is ever invented for a QB change.
LEAN_BLOCK_QB_UNVERIFIED = "NO_LEAN:QB_STARTER_UNVERIFIED"


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
    prop_keys = {_name_key(n) for n in prop_qbs}
    ctx["qb_verified"] = {
        team: bool(team in qbs and _name_key(qbs[team]["qb"]) in prop_keys)
        for team in (away, home)
    }
    return ctx


def qb_lean_block(ctx: dict) -> str | None:
    """CHANGE when a DK QB prop names a non-last-starter; UNVERIFIED unless
    both teams' last listed starters are corroborated by DK QB props."""
    if ctx.get("qb_change_flag"):
        return LEAN_BLOCK_QB_CHANGE
    verified = ctx.get("qb_verified") or {}
    if len(verified) != 2 or not all(verified.values()):
        return LEAN_BLOCK_QB_UNVERIFIED
    return None


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


def _schedule_team(name: object) -> str | None:
    from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team
    try:
        return resolve_team(str(name or ""))
    except NflTeamAliasError:
        return None


def schedule_kickoff(schedule: list, *, away: str, home: str) -> str:
    """Kickoff for away@home from an independent schedule. Exactly one match or refuse."""
    from sportsedge.nfl_public_schedule import _parse_iso
    hits = [row for row in schedule or []
            if isinstance(row, dict)
            and _schedule_team(row.get("away_team")) == away
            and _schedule_team(row.get("home_team")) == home]
    if not hits:
        raise ResidualQuoteError("SCHEDULE_KICKOFF:NO_MATCH")
    if len(hits) != 1:
        raise ResidualQuoteError("SCHEDULE_KICKOFF:AMBIGUOUS")
    try:
        return _parse_iso(str(hits[0]["commence_time"])).isoformat()
    except (KeyError, TypeError, ValueError) as exc:
        raise ResidualQuoteError("SCHEDULE_KICKOFF:INVALID") from exc


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
    ap.add_argument("--as-of", default="",
                    help="pricing clock (the workflow passes its own run time); default: ticket observed_at for replay")
    ap.add_argument("--schedule", default="",
                    help="independent schedule JSON (fetch_nfl_events rows); kickoff comes only from here")
    ap.add_argument("--fetch-espn-schedule", action="store_true",
                    help="fetch the ESPN public scoreboard for kickoffs; fetch failure refuses pricing")
    args = ap.parse_args()
    ticket = json.loads(Path(args.input).read_text(encoding="utf-8"))
    history = _history_rows(json.loads(Path(args.history).read_text(encoding="utf-8")) if args.history else [])
    runtime = load_runtime()
    residual_policy = load_frozen_policy()
    asof = date.fromisoformat(str(ticket.get("slate") or date.today().isoformat()))
    # Pricing clock. The issue's edit time is never a quote capture time; the
    # workflow passes its run time so the 180 s quote TTL measures real age.
    pricing_as_of = args.as_of or ticket.get("observed_at")
    schedule: list | None = None
    schedule_error: str | None = None
    if args.schedule:
        schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    elif args.fetch_espn_schedule:
        try:
            from sportsedge.nfl_public_schedule import fetch_nfl_events
            schedule = fetch_nfl_events()
        except Exception:  # noqa: BLE001 - any fetch failure refuses pricing
            schedule, schedule_error = [], "SCHEDULE_KICKOFF:UNAVAILABLE"
    games_out = []
    for game in ticket.get("games") or []:
        feat = recency_features(history, home=str(game["home"]), away=str(game["away"]), asof=asof) if history else {"ok": False, "reason": "NO_MODEL:INSUFFICIENT_PRIOR_GAMES"}
        forecast = raw_forecasts(runtime, feat["vector"]) if feat.get("ok") else None
        markets = []
        picks = []  # No validated game market. Research rows never promote.
        leans = []
        residual_rows = []
        residual_error = None
        if schedule is not None:
            # Independent kickoff only; a ticket-supplied time is discarded.
            game = {**game, "commence_time": None}
            try:
                if schedule_error:
                    raise ResidualQuoteError(schedule_error)
                game["commence_time"] = schedule_kickoff(schedule, away=str(game["away"]), home=str(game["home"]))
            except ResidualQuoteError as exc:
                residual_error = str(exc)
        if residual_error is None and feat.get("ok") and forecast is not None:
            try:
                residual_rows = price_game(
                    game, raw_model_margin=forecast["margin"],
                    raw_model_total=forecast["total"],
                    as_of=pricing_as_of,
                    policy=residual_policy,
                )
            except ResidualQuoteError as exc:
                residual_error = str(exc)
        elif residual_error is None:
            residual_error = str(feat.get("reason") or "NO_PRIOR_MODEL_HISTORY")

        context = game_context(game, history, asof, feat, forecast)
        qb_block = qb_lean_block(context)
        for raw in game.get("markets") or []:
            key = str(raw.get("market") or "").lower()
            if key not in {"moneyline", "spread", "total"}:
                markets.append({**raw, "no_model": market_eligibility(key, raw.get("line"))})
                continue
            if residual_error is not None:
                markets.append({**raw, "no_model": "NO_MODEL:RESIDUAL_QUOTES_OR_HISTORY_UNAVAILABLE",
                                "residual_research_error": residual_error})
                continue
            choices = [x for x in residual_rows if x["market"] == key]
            if len(choices) != 2:
                markets.append({**raw, "no_model": "NO_MODEL:PAIRED_RESIDUAL_PRICE_UNAVAILABLE"})
                continue
            # Existing floors remain 2pp probability edge AND 2% net EV.
            # Additional point threshold blocks trivial residual displacement.
            adjustment = (choices[0]["fair_total"] - float(raw["line"])
                          if key == "total" else
                          choices[0]["fair_margin"] - float(next(
                              m["line"] for m in game["markets"] if m["market"] == "spread")))
            qualified = [
                x for x in choices if
                x["edge_probability_points"] > float(residual_policy["min_edge_probability_points"])
                and x["ev_per_dollar"] > float(residual_policy["min_ev_per_dollar"])
                and x["price_american"] >= -165
                and abs(adjustment) >= float(residual_policy["forward_track_min_abs_adjustment_points"])
            ]
            lean = max(qualified, key=lambda x: (x["ev_per_dollar"], x["edge_probability_points"])) if qualified else None
            lean_block = None
            if qb_block:
                lean, lean_block = None, qb_block
            if lean:
                lean = {**lean, "lean_only": True,
                        "lean_reason": "RESEARCH_ONLY:MARKET_ANCHORED_RESIDUAL_FORWARD_CLV_PENDING",
                        "score_0_100": qualification_role_score({
                            "model_ready": True, "pit_safe": True, "role_stable": True,
                            "usage_supported": False, "matchup_supported": True,
                            "injury_context_ready": False, "shared_simulation_ready": True,
                            "market_binding_ready": True,
                        })}
                leans.append(lean)
            markets.append({**raw, "no_model": None, "pick": None, "lean": lean,
                            "lean_block": lean_block,
                            "residual_mode": True,
                            "residual_research_prices": choices,
                            "residual_research_adjustment": adjustment})
        games_out.append({**game, "markets": markets, "picks": picks, "leans": leans,
                          "residual_research_prices": residual_rows,
                          "residual_research_error": residual_error,
                          "features": feat, "context": context})
    payload = {
        "sport": "NFL",
        "context_bound": False,
        "games": games_out,
        "bet_proven_markets": sorted(BET_PROVEN_MARKETS),
        "residual_research_policy": "PRECOMMITTED_RESEARCH_PRIOR_NOT_HISTORICALLY_FITTED",
        "validated_markets": [],
        "pricing_as_of": pricing_as_of,
        "empty_reason": None if any(g["picks"] for g in games_out) else (
            "No qualified bets: residual market-anchored prices are RESEARCH ONLY. "
            "Forward CLV evidence is pending; leans are not validated bets."
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
