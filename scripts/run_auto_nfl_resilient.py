#!/usr/bin/env python3
"""NFL card runner shaped like scripts/run_auto_mlb_resilient.py.

User-supplied lines only. No Odds API. A row with model_p and positive edge is a
bet. A no-edge slate is success. Zero quotes is the only infrastructure block.

Sides are priced from the frozen attempt-9 market-blind margin/total when a
history file or row forecast is present. Missing forecasts leave model_p unset;
they are not an infrastructure failure.
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

from sportsedge.football_full_board import build_football_full_board
from sportsedge.nfl_attempt9_live_forecast import load_model_p, load_runtime, raw_forecasts, recency_features

SPREAD_SIGMA_FALLBACK = 13.78774897397055
TOTAL_SIGMA_FALLBACK = 13.99738332096112


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
    market = str(quote.get("market") or "MONEYLINE").upper()
    side = str(quote.get("side") or quote.get("selection") or "").upper()
    if market in {"MONEYLINE", "ML", "H2H"}:
        home_p = _phi(margin / spread_sigma)
        if side in {"HOME", "H"}:
            return home_p
        if side in {"AWAY", "A"}:
            return 1.0 - home_p
        return None
    if market in {"SPREAD", "ALT_SPREAD", "ALTERNATE_SPREAD"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"HOME", "AWAY"}:
            return None
        # Home handicap is stored as the home line. Away line is the negation.
        home_line = float(line) if side == "HOME" else -float(line)
        cover = _phi((margin + home_line) / spread_sigma)
        return cover if side == "HOME" else 1.0 - cover
    if market in {"TOTAL", "TOTALS", "ALT_TOTAL", "ALTERNATE_TOTAL"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"OVER", "UNDER"}:
            return None
        over = _phi((total - float(line)) / total_sigma)
        return over if side == "OVER" else 1.0 - over
    return None


def _forecasts(rows: list, history_path: str | None) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
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
    return out


def build_card(rows: list, *, history_path: str | None = None) -> dict:
    spread_sigma, total_sigma, sigma_source = _sigmas()
    forecasts = _forecasts(rows, history_path)
    results = []
    quote_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("game_id") or f"{row.get('away_team') or row.get('away')}@{row.get('home_team') or row.get('home')}")
        quotes = list(row.get("quotes") or row.get("markets") or [])
        if not quotes and row.get("american_odds") is not None:
            quotes = [row]
        quote_rows += len(quotes)
        margin_total = forecasts.get(key)
        for quote in quotes:
            model_p = quote.get("model_p", row.get("model_p"))
            if model_p is None and margin_total is not None:
                model_p = _side_probability(margin_total[0], margin_total[1], quote, spread_sigma, total_sigma)
            odds = quote.get("american_odds", quote.get("price_american"))
            edge = None
            if model_p is not None and odds is not None:
                edge = float(model_p) - _american_implied(float(odds))
            is_bet = model_p is not None and edge is not None and edge > 0
            results.append({
                "game_id": row.get("game_id") or quote.get("game_id") or key,
                "home_team": row.get("home_team") or row.get("home"),
                "away_team": row.get("away_team") or row.get("away"),
                "market": quote.get("market") or "MONEYLINE",
                "side": quote.get("side") or quote.get("selection"),
                "line": quote.get("line", quote.get("point")),
                "american_odds": odds,
                "model_p": None if model_p is None else float(model_p),
                "edge": edge,
                "bet_status": "BET" if is_bet else "NO_BET",
                "reason": "EDGE_POSITIVE" if is_bet else ("NO_EDGE" if model_p is not None else "MODEL_P_UNAVAILABLE"),
            })
    bets = [row for row in results if row.get("bet_status") == "BET"]
    blocked = quote_rows == 0
    game_rows = [
        {
            "game_id": row["game_id"],
            "market": str(row["market"]).lower(),
            "side": row["side"],
            "line": row["line"],
            "american_odds": row["american_odds"],
            "model_p": row["model_p"],
            "edge": row["edge"],
            "reason": row["reason"],
        }
        for row in results
    ]
    board = build_football_full_board(sport="NFL", game_rows=game_rows) if game_rows else {"rows": [], "summary": {}}
    return {
        "schema_version": "NFL_LIVE_CARD_V1",
        "status": "BLOCKED_NO_ODDS" if blocked else "SUCCESS",
        "run_status": "BLOCKED_NO_ODDS" if blocked else "READY",
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
        "odds_api_called": False,
        "sigma_source": sigma_source,
        "spread_sigma": spread_sigma,
        "total_sigma": total_sigma,
        "results": results,
        "bets": bets,
        "board": board,
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
            "odds_api_called": False,
        },
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
        rows = _load_board(raw)
        payload = build_card(rows, history_path=history or None)
    except Exception as exc:
        payload = {
            "schema_version": "NFL_LIVE_CARD_V1",
            "run_status": "BLOCKED",
            "status": "BLOCKED",
            "results": [],
            "bets": [],
            "odds_api_called": False,
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
            "funnel": {"odds_rows_fetched": 0, "bets_emitted": 0, "pipeline_health": "BROKEN"},
        }
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    board_path = Path(args.board_output)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(json.dumps(payload.get("board") or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_status": payload["run_status"], "funnel": payload["funnel"]}, sort_keys=True))
    return 2 if payload.get("run_status") == "BLOCKED_NO_ODDS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
