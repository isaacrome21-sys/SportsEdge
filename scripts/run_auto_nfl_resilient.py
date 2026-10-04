#!/usr/bin/env python3
"""NFL card runner — sides, spread, totals, alt lines, SGP legs.

User-supplied lines only. No Odds API. Every prop, side, and total family is
emitted on both sides. A complement is priced only from a supplied opposite
quote. Missing families stay explicit blockers.

SGP legs are priced individually using the same sigma model. Correlation
between legs is NOT modeled — the card notes this explicitly. SGP leg output
is informational only and does not grant staking authority.

This does not edit the frozen NFL M2 run machine and does not create
Model_P, Truth Gate, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_full_board import (
    PROVIDER_TO_SURFACE,
    SIDE_MARKETS,
    TOTAL_MARKETS,
    build_football_full_board,
    catalog_complete,
)
from sportsedge.nfl_attempt9_live_forecast import load_model_p, load_runtime, raw_forecasts, recency_features

SPREAD_SIGMA_FALLBACK = 13.78774897397055
TOTAL_SIGMA_FALLBACK  = 13.99738332096112

# All market keys DK uses — mapped to canonical surface name
GAME_MARKETS: dict[str, str] = {
    # moneyline
    "moneyline":             "moneyline",
    "ml":                    "moneyline",
    "h2h":                   "moneyline",
    # spread (main + alts)
    "spread":                "spread",
    "spreads":               "spread",
    "alt_spread":            "alternate_spread",
    "alternate_spread":      "alternate_spread",
    # total (main + alts)
    "total":                 "total",
    "totals":                "total",
    "alt_total":             "alternate_total",
    "alt_totals":            "alternate_total",
    "alternate_total":       "alternate_total",
    # team totals
    "team_total":            "team_total",
    "team_totals":           "team_total",
    # first half
    "first_half_moneyline":  "first_half_moneyline",
    "first_half_spread":     "first_half_spread",
    "first_half_total":      "first_half_total",
    # second half
    "second_half_moneyline": "second_half_moneyline",
    "second_half_spread":    "second_half_spread",
    "second_half_total":     "second_half_total",
    # quarter
    "quarter_moneyline":     "quarter_moneyline",
    "quarter_spread":        "quarter_spread",
    "quarter_total":         "quarter_total",
}


def _american_implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _phi(z: float) -> float:
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def _load_board(raw: str | None) -> list:
    text = str(raw or "").strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = (
            payload.get("events")
            or payload.get("rows")
            or payload.get("games")
            or payload.get("board")
            or []
        )
    if not isinstance(payload, list):
        raise ValueError("NFL_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    return payload


def _load_sgp_legs(raw: str | None) -> list:
    """Parse optional SGP legs JSON — array of quote-shaped objects."""
    text = str(raw or "").strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("legs") or payload.get("rows") or []
    if not isinstance(payload, list):
        raise ValueError("NFL_AUTO_SGP_LEGS_ARRAY_REQUIRED")
    return [row for row in payload if isinstance(row, dict)]


def _sigmas() -> tuple[float, float, str]:
    try:
        artifact = load_model_p()
        markets = artifact.get("markets") or {}
        return float(markets["spread"]["sigma"]), float(markets["total"]["sigma"]), "ATTEMPT9_SIGMA"
    except Exception:
        return SPREAD_SIGMA_FALLBACK, TOTAL_SIGMA_FALLBACK, "ATTEMPT9_SIGMA_FALLBACK"


def _side_probability(
    margin: float,
    total: float,
    surface_market: str,
    side: str,
    line: float | None,
    spread_sigma: float,
    total_sigma: float,
) -> float | None:
    """Price any side/spread/total market through the sigma model."""
    s = surface_market
    sd = side.upper()

    # moneyline family (half/quarter get tighter sigma)
    if s in {"moneyline", "first_half_moneyline", "second_half_moneyline", "quarter_moneyline"}:
        sigma = spread_sigma * (0.65 if "half" in s else 0.45 if "quarter" in s else 1.0)
        home_p = _phi(margin / sigma)
        if sd in {"HOME", "H"}:   return home_p
        if sd in {"AWAY", "A"}:   return 1.0 - home_p
        return None

    # spread family (main + alts + halves + quarters)
    if s in {"spread", "alternate_spread", "first_half_spread", "second_half_spread", "quarter_spread"}:
        if line is None or sd not in {"HOME", "AWAY"}:
            return None
        sigma = spread_sigma * (0.65 if "half" in s else 0.45 if "quarter" in s else 1.0)
        home_line = float(line) if sd == "HOME" else -float(line)
        cover = _phi((margin + home_line) / sigma)
        return cover if sd == "HOME" else 1.0 - cover

    # total family (main + alts + team + halves + quarters)
    if s in {"total", "alternate_total", "team_total",
             "first_half_total", "second_half_total", "quarter_total"}:
        if line is None or sd not in {"OVER", "UNDER"}:
            return None
        # team totals: approximate as ~45% of game total
        ref = total * 0.45 if s == "team_total" else total
        sigma = total_sigma * (0.65 if "half" in s else 0.45 if "quarter" in s else 1.0)
        over = _phi((ref - float(line)) / sigma)
        return over if sd == "OVER" else 1.0 - over

    return None


def _forecasts(rows: list, history_path: str | None) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(
            row.get("game_id")
            or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}"
        )
        if row.get("margin") is not None and row.get("total") is not None:
            out[key] = (float(row["margin"]), float(row["total"]))
        elif row.get("home_mean") is not None and row.get("away_mean") is not None:
            home = float(row["home_mean"])
            away = float(row["away_mean"])
            out[key] = (home - away, home + away)
    if not history_path:
        return out
    history_raw = json.loads(Path(history_path).read_text(encoding="utf-8"))
    history = history_raw.get("games") if isinstance(history_raw, dict) else history_raw
    if not isinstance(history, list):
        return out
    runtime = load_runtime()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(
            row.get("game_id")
            or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}"
        )
        if key in out:
            continue
        home = str(row.get("home_team") or row.get("home") or "")
        away = str(row.get("away_team") or row.get("away") or "")
        if not home or not away:
            continue
        asof = date.fromisoformat(str(row.get("slate") or date.today().isoformat()))
        feat = recency_features(history, home=home, away=away, asof=asof)
        if not feat.get("ok"):
            continue
        forecast = raw_forecasts(runtime, feat["vector"])
        out[key] = (float(forecast["margin"]), float(forecast["total"]))
    return out


def _quotes(row: dict) -> list[dict]:
    quotes = list(row.get("quotes") or row.get("markets") or [])
    if not quotes and row.get("american_odds") is not None:
        quotes = [row]
    return [q for q in quotes if isinstance(q, dict)]


def _price_quote(
    quote: dict,
    game_row: dict,
    margin_total: tuple[float, float] | None,
    spread_sigma: float,
    total_sigma: float,
) -> dict:
    """Return a fully-priced result dict for one quote."""
    raw_market = str(
        quote.get("market") or quote.get("provider_market") or "moneyline"
    ).strip().lower()
    surface_market = GAME_MARKETS.get(raw_market, raw_market)
    side = str(quote.get("side") or quote.get("selection") or "").upper()
    line_raw = quote.get("line", quote.get("point"))
    line = float(line_raw) if line_raw is not None else None
    odds_raw = quote.get("american_odds", quote.get("price_american"))
    odds = float(odds_raw) if odds_raw is not None else None
    game_id = (
        quote.get("game_id")
        or game_row.get("game_id")
        or f"{game_row.get('away_team') or game_row.get('away')}@{game_row.get('home_team') or game_row.get('home')}"
    )

    model_p = quote.get("model_p", game_row.get("model_p"))
    if model_p is None and margin_total is not None:
        model_p = _side_probability(
            margin_total[0], margin_total[1],
            surface_market, side, line,
            spread_sigma, total_sigma,
        )

    edge = None
    if model_p is not None and odds is not None:
        edge = float(model_p) - _american_implied(float(odds))

    is_bet = model_p is not None and edge is not None and edge > 0
    return {
        "game_id":       game_id,
        "home_team":     game_row.get("home_team") or game_row.get("home"),
        "away_team":     game_row.get("away_team") or game_row.get("away"),
        "market":        surface_market,
        "raw_market":    raw_market,
        "side":          side,
        "line":          line,
        "american_odds": odds,
        "opposite_odds": quote.get("opposite_odds"),
        "model_p":       None if model_p is None else float(model_p),
        "edge":          edge,
        "bet_status":    "BET" if is_bet else "NO_BET",
        "reason": (
            "EDGE_POSITIVE" if is_bet
            else ("NO_EDGE" if model_p is not None else "MODEL_P_UNAVAILABLE")
        ),
        "official_eligible": False,
    }


def build_card(
    rows: list,
    *,
    history_path: str | None = None,
    sgp_legs: list | None = None,
) -> dict:
    spread_sigma, total_sigma, sigma_source = _sigmas()
    forecasts = _forecasts(rows, history_path)
    results: list[dict] = []
    game_rows_board: list[dict] = []
    prop_rows_board: list[dict] = []
    quote_rows = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(
            row.get("game_id")
            or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}"
        )
        margin_total = forecasts.get(key)

        for quote in _quotes(row):
            quote_rows += 1
            result = _price_quote(quote, row, margin_total, spread_sigma, total_sigma)
            results.append(result)

            raw_market    = result["raw_market"]
            surface_market = result["market"]
            payload = {
                "game_id":       result["game_id"],
                "entity_id":     quote.get("entity_id") or quote.get("player_id") or quote.get("player_name"),
                "team_side":     quote.get("team_side"),
                "side":          result["side"],
                "line":          result["line"],
                "american_odds": result["american_odds"],
                "opposite_odds": result["opposite_odds"],
                "model_p":       result["model_p"],
                "reason":        result["reason"],
            }

            if raw_market in PROVIDER_TO_SURFACE or quote.get("provider_market"):
                prop_rows_board.append({
                    **payload,
                    "provider_market": quote.get("provider_market") or raw_market,
                })
            elif (
                surface_market in GAME_MARKETS.values()
                or surface_market in SIDE_MARKETS
                or surface_market in TOTAL_MARKETS
            ):
                game_rows_board.append({**payload, "market": surface_market})

    # ---- SGP legs — priced independently ----
    sgp_results: list[dict] = []
    for idx, leg in enumerate(sgp_legs or []):
        game_id = str(leg.get("game_id") or "UNKNOWN")
        result = _price_quote(leg, leg, forecasts.get(game_id), spread_sigma, total_sigma)
        result["leg_index"] = idx
        result["sgp_leg"] = True
        result["correlation_note"] = (
            "UNCORRELATED_INDEPENDENT_PRICE — SGP true probability requires "
            "joint simulation; this is a per-leg floor only."
        )
        sgp_results.append(result)

    board = build_football_full_board(
        sport="NFL",
        game_rows=game_rows_board,
        prop_rows=prop_rows_board,
    )

    bets     = [r for r in results    if r.get("bet_status") == "BET"]
    sgp_bets = [r for r in sgp_results if r.get("bet_status") == "BET"]
    blocked  = quote_rows == 0 and not sgp_results

    return {
        "schema_version":      "NFL_LIVE_CARD_V2",
        "status":              "BLOCKED_NO_ODDS" if blocked else "SUCCESS",
        "run_status":          "BLOCKED_NO_ODDS" if blocked else "READY",
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
        "odds_api_called":     False,
        "sigma_source":        sigma_source,
        "spread_sigma":        spread_sigma,
        "total_sigma":         total_sigma,
        "results":             results,
        "bets":                bets,
        "sgp_legs":            sgp_results,
        "sgp_bets":            sgp_bets,
        "full_board":          board,
        "summary": {
            "both_sides":       board["summary"]["both_sides"],
            "side_rows":        board["summary"]["side_rows"],
            "total_rows":       board["summary"]["total_rows"],
            "prop_rows":        board["summary"]["prop_rows"],
            "catalog_complete": catalog_complete(board["summary"]),
        },
        "funnel": {
            "odds_rows_fetched":  quote_rows,
            "model_priced":       sum(r.get("model_p") is not None for r in results),
            "edge_positive":      len(bets),
            "bets_emitted":       len(bets),
            "sgp_legs_parsed":    len(sgp_results),
            "sgp_edge_positive":  len(sgp_bets),
            "pipeline_health":    "BROKEN" if blocked else "OK",
            "pipeline_health_reason": (
                "NO_ODDS_ROWS_REACHED_PRICING" if blocked else "OK"
            ),
        },
        "governance": {
            "truth_gate":                    False,
            "official_model_p":              False,
            "official_authority":            False,
            "odds_api_called":               False,
            "frozen_nfl_run_machine_edited": False,
            "sgp_correlation_modeled":       False,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",       default="artifacts/live_nfl_card.json")
    parser.add_argument("--board",        default="")
    parser.add_argument("--history",      default="")
    parser.add_argument("--sgp-legs",     default="")
    parser.add_argument("--board-output", default="artifacts/live_nfl_board.json")
    args = parser.parse_args()

    raw     = args.board    or os.environ.get("SPORTSEDGE_NFL_BOARD",    "")
    history = args.history  or os.environ.get("SPORTSEDGE_NFL_HISTORY", "")
    raw_sgp = args.sgp_legs or os.environ.get("SPORTSEDGE_NFL_SGP_LEGS", "")

    try:
        board_rows = _load_board(raw)
        sgp_legs   = _load_sgp_legs(raw_sgp)
        payload    = build_card(board_rows, history_path=history or None, sgp_legs=sgp_legs)
    except Exception as exc:
        from sportsedge.football_full_board import board_from_machine_results
        board = board_from_machine_results("NFL", [])
        payload = {
            "schema_version": "NFL_LIVE_CARD_V2",
            "run_status":     "BLOCKED",
            "status":         "BLOCKED",
            "results":        [],
            "bets":           [],
            "sgp_legs":       [],
            "sgp_bets":       [],
            "full_board":     board,
            "summary": {
                "both_sides":       board["summary"]["both_sides"],
                "side_rows":        board["summary"]["side_rows"],
                "total_rows":       board["summary"]["total_rows"],
                "prop_rows":        board["summary"]["prop_rows"],
                "catalog_complete": catalog_complete(board["summary"]),
            },
            "odds_api_called":  False,
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
            "funnel": {
                "odds_rows_fetched": 0,
                "bets_emitted":      0,
                "sgp_legs_parsed":   0,
                "pipeline_health":   "BROKEN",
            },
            "governance": {
                "truth_gate":         False,
                "official_authority": False,
                "odds_api_called":    False,
            },
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"run_status": payload["run_status"], "summary": payload["summary"]}, sort_keys=True))
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    board_path = Path(args.board_output)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(
        json.dumps(payload.get("full_board") or {}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "run_status": payload["run_status"],
        "summary":    payload["summary"],
        "funnel":     payload["funnel"],
    }, sort_keys=True))
    return 2 if payload.get("run_status") == "BLOCKED_NO_ODDS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
