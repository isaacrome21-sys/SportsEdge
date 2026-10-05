#!/usr/bin/env python3
"""NFL card runner shaped like the MLB auto card.

User-supplied lines only. No Odds API. Every prop, side, and total family is
emitted on both sides. A complement is priced only from a supplied opposite
quote. Missing families stay explicit blockers. This does not edit the frozen
NFL M2 run machine and does not create Model_P, Truth Gate, or OFFICIAL authority.
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
TOTAL_SIGMA_FALLBACK = 13.99738332096112
# Attempt-9 intercepts (z=0). A model mean, not a line. Used only when the
# manual board does not include history or an explicit margin/total.
ATTEMPT9_BASELINE_MARGIN = 2.4899289099525883
ATTEMPT9_BASELINE_TOTAL = 45.492298578199055
GAME_MARKETS = {
    "moneyline": "moneyline",
    "ml": "moneyline",
    "h2h": "moneyline",
    "spread": "spread",
    "alt_spread": "alternate_spread",
    "alternate_spread": "alternate_spread",
    "total": "total",
    "totals": "total",
    "alt_total": "alternate_total",
    "alternate_total": "alternate_total",
    "team_total": "team_total",
    "team_totals": "team_total",
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
        payload = payload.get("events") or payload.get("rows") or payload.get("games") or payload.get("board") or []
    if not isinstance(payload, list):
        raise ValueError("NFL_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    return payload


def _sigmas() -> tuple[float, float, str]:
    try:
        artifact = load_model_p()
        markets = artifact.get("markets") or {}
        return float(markets["spread"]["sigma"]), float(markets["total"]["sigma"]), "ATTEMPT9_SIGMA"
    except Exception:
        return SPREAD_SIGMA_FALLBACK, TOTAL_SIGMA_FALLBACK, "ATTEMPT9_SIGMA_FALLBACK"


def _side_probability(margin: float, total: float, quote: dict, spread_sigma: float, total_sigma: float) -> float | None:
    market = str(quote.get("market") or "moneyline").strip().lower()
    side = str(quote.get("side") or quote.get("selection") or "").upper()
    if market in {"moneyline", "ml", "h2h"}:
        home_p = _phi(margin / spread_sigma)
        if side in {"HOME", "H"}:
            return home_p
        if side in {"AWAY", "A"}:
            return 1.0 - home_p
        return None
    if market in {"spread", "alt_spread", "alternate_spread"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"HOME", "AWAY"}:
            return None
        home_line = float(line) if side == "HOME" else -float(line)
        cover = _phi((margin + home_line) / spread_sigma)
        return cover if side == "HOME" else 1.0 - cover
    if market in {"total", "totals", "alt_total", "alternate_total", "team_total", "team_totals"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"OVER", "UNDER"}:
            return None
        over = _phi((total - float(line)) / total_sigma)
        return over if side == "OVER" else 1.0 - over
    return None


def _forecasts(rows: list, history_path: str | None) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    out: dict[str, tuple[float, float]] = {}
    source: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
        if row.get("margin") is not None and row.get("total") is not None:
            out[key] = (float(row["margin"]), float(row["total"]))
            source[key] = "BOARD_MARGIN_TOTAL"
        elif row.get("home_mean") is not None and row.get("away_mean") is not None:
            home = float(row["home_mean"])
            away = float(row["away_mean"])
            out[key] = (home - away, home + away)
            source[key] = "BOARD_TEAM_MEANS"
    if not history_path:
        return _fill_baseline(rows, out, source)
    history_raw = json.loads(Path(history_path).read_text(encoding="utf-8"))
    history = history_raw.get("games") if isinstance(history_raw, dict) else history_raw
    if not isinstance(history, list):
        return out
    runtime = load_runtime()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
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
        source[key] = "ATTEMPT9_HISTORY"
    return _fill_baseline(rows, out, source)


def _fill_baseline(rows: list, out: dict, source: dict) -> tuple[dict, dict]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
        if key in out:
            continue
        out[key] = (ATTEMPT9_BASELINE_MARGIN, ATTEMPT9_BASELINE_TOTAL)
        source[key] = "ATTEMPT9_INTERCEPT_BASELINE"
    return out, source


def _quotes(row: dict) -> list[dict]:
    quotes = list(row.get("quotes") or row.get("markets") or [])
    if not quotes and row.get("american_odds") is not None:
        quotes = [row]
    return [quote for quote in quotes if isinstance(quote, dict)]


def build_card(rows: list, *, history_path: str | None = None) -> dict:
    spread_sigma, total_sigma, sigma_source = _sigmas()
    forecasts, forecast_source = _forecasts(rows, history_path)
    results = []
    game_rows = []
    prop_rows = []
    quote_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
        margin_total = forecasts.get(key)
        for quote in _quotes(row):
            quote_rows += 1
            market = str(quote.get("market") or quote.get("provider_market") or "moneyline").strip().lower()
            side = str(quote.get("side") or quote.get("selection") or "").upper()
            supplied_model_p = quote.get("model_p", row.get("model_p"))
            model_p = supplied_model_p
            if model_p is None and margin_total is not None and market in GAME_MARKETS:
                model_p = _side_probability(margin_total[0], margin_total[1], quote, spread_sigma, total_sigma)
            baseline_only = (
                supplied_model_p is None
                and forecast_source.get(key) == "ATTEMPT9_INTERCEPT_BASELINE"
                and model_p is not None
            )
            odds = quote.get("american_odds", quote.get("price_american"))
            raw_edge = None
            if model_p is not None and odds is not None:
                raw_edge = float(model_p) - _american_implied(float(odds))
            edge = None if baseline_only else raw_edge
            is_bet = model_p is not None and edge is not None and edge > 0
            result = {
                "game_id": row.get("game_id") or quote.get("game_id") or key,
                "home_team": row.get("home_team") or row.get("home"),
                "away_team": row.get("away_team") or row.get("away"),
                "market": market,
                "side": side,
                "line": quote.get("line", quote.get("point")),
                "american_odds": odds,
                "opposite_odds": quote.get("opposite_odds"),
                "model_p": None if model_p is None else float(model_p),
                "edge": edge,
                "research_edge": raw_edge if baseline_only else None,
                "bet_status": "TRACK" if baseline_only else ("BET" if is_bet else "NO_BET"),
                "reason": (
                    "INTERCEPT_BASELINE_ONLY"
                    if baseline_only
                    else ("EDGE_POSITIVE" if is_bet else ("NO_EDGE" if model_p is not None else "MODEL_P_UNAVAILABLE"))
                ),
                "forecast_source": forecast_source.get(key),
                "official_eligible": False,
            }
            results.append(result)
            payload = {
                "game_id": result["game_id"],
                "entity_id": quote.get("entity_id") or quote.get("player_id") or quote.get("player_name"),
                "team_side": quote.get("team_side"),
                "side": side,
                "line": result["line"],
                "american_odds": odds,
                "opposite_odds": quote.get("opposite_odds"),
                "model_p": result["model_p"],
                "reason": result["reason"],
            }
            if market in PROVIDER_TO_SURFACE or quote.get("provider_market"):
                prop_rows.append({**payload, "provider_market": quote.get("provider_market") or market})
            elif market in GAME_MARKETS or market in SIDE_MARKETS or market in TOTAL_MARKETS:
                game_rows.append({**payload, "market": GAME_MARKETS.get(market, market)})
    board = build_football_full_board(sport="NFL", game_rows=game_rows, prop_rows=prop_rows)
    bets = [row for row in results if row.get("bet_status") == "BET"]
    blocked = quote_rows == 0
    return {
        "schema_version": "NFL_LIVE_CARD_V1",
        "status": "BLOCKED_NO_ODDS" if blocked else "SUCCESS",
        "run_status": "BLOCKED_NO_ODDS" if blocked else "READY",
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
        "odds_api_called": False,
        "sigma_source": sigma_source,
        "forecast_source": "ATTEMPT9_INTERCEPT_BASELINE" if any(v == "ATTEMPT9_INTERCEPT_BASELINE" for v in forecast_source.values()) else "ATTEMPT9_OR_BOARD",
        "spread_sigma": spread_sigma,
        "total_sigma": total_sigma,
        "results": results,
        "bets": bets,
        "full_board": board,
        "summary": {
            "both_sides": board["summary"]["both_sides"],
            "side_rows": board["summary"]["side_rows"],
            "total_rows": board["summary"]["total_rows"],
            "prop_rows": board["summary"]["prop_rows"],
            "catalog_complete": catalog_complete(board["summary"]),
        },
        "funnel": {
            "odds_rows_fetched": quote_rows,
            "model_priced": sum(row.get("model_p") is not None for row in results),
            "edge_positive": len(bets),
            "bets_emitted": len(bets),
            "pipeline_health": "BROKEN" if blocked else "OK",
            "pipeline_health_reason": "NO_ODDS_ROWS_REACHED_PRICING" if blocked else "OK",
        },
        "governance": {
            "truth_gate": False,
            "official_model_p": False,
            "official_authority": False,
            "odds_api_called": False,
            "frozen_nfl_run_machine_edited": False,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/live_nfl_card.json")
    parser.add_argument("--board", default="")
    parser.add_argument("--history", default="")
    parser.add_argument("--board-output", default="artifacts/live_nfl_board.json")
    args = parser.parse_args()
    raw = args.board or os.environ.get("SPORTSEDGE_NFL_BOARD", "")
    history = args.history or os.environ.get("SPORTSEDGE_NFL_HISTORY", "")
    try:
        payload = build_card(_load_board(raw), history_path=history or None)
    except Exception as exc:
        from sportsedge.football_full_board import board_from_machine_results
        board = board_from_machine_results("NFL", [])
        payload = {
            "schema_version": "NFL_LIVE_CARD_V1",
            "run_status": "BLOCKED",
            "status": "BLOCKED",
            "results": [],
            "bets": [],
            "full_board": board,
            "summary": {
                "both_sides": board["summary"]["both_sides"],
                "side_rows": board["summary"]["side_rows"],
                "total_rows": board["summary"]["total_rows"],
                "prop_rows": board["summary"]["prop_rows"],
                "catalog_complete": catalog_complete(board["summary"]),
            },
            "odds_api_called": False,
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
            "funnel": {"odds_rows_fetched": 0, "bets_emitted": 0, "pipeline_health": "BROKEN"},
            "governance": {"truth_gate": False, "official_authority": False, "odds_api_called": False},
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
    board_path.write_text(json.dumps(payload.get("full_board") or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_status": payload["run_status"], "summary": payload["summary"], "funnel": payload["funnel"]}, sort_keys=True))
    return 2 if payload.get("run_status") == "BLOCKED_NO_ODDS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
