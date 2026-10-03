#!/usr/bin/env python3
"""NHL card runner shaped like scripts/run_auto_mlb_resilient.py.

User-supplied lines only. No Odds API. A row with model_p and positive edge is a
bet. A no-edge slate is success. Zero quotes is the only infrastructure block.

Regulation rates come from the board or from the public baseline when a completed
history file is supplied. Missing rates leave model_p null; they do not invent lines.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nhl.markets import game_total_over, home_moneyline, home_puck_line
from sportsedge.sports.nhl.simulation import NHLGameState, simulate_game_paths


def _american_implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _load_board(raw: str | None) -> list:
    text = str(raw or "").strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        games = payload.get("games")
        if isinstance(games, list):
            return games
        payload = payload.get("events") or payload.get("rows") or payload.get("board") or []
    if not isinstance(payload, list):
        raise ValueError("NHL_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    return payload


def _quotes_for(row: dict) -> list[dict]:
    quotes = row.get("quotes")
    if isinstance(quotes, list) and quotes:
        return [q for q in quotes if isinstance(q, dict)]
    markets = row.get("markets")
    if isinstance(markets, list) and markets:
        out = []
        for market in markets:
            if not isinstance(market, dict):
                continue
            name = str(market.get("market") or "MONEYLINE").upper()
            line = market.get("line")
            if market.get("away_or_over_price") is not None:
                side = "OVER" if name == "TOTAL" else "AWAY"
                out.append({"market": name, "side": side, "line": line, "american_odds": market["away_or_over_price"]})
            if market.get("home_or_under_price") is not None:
                side = "UNDER" if name == "TOTAL" else "HOME"
                out.append({"market": name, "side": side, "line": line, "american_odds": market["home_or_under_price"]})
        return out
    if row.get("american_odds") is not None:
        return [row]
    return []


def _rates(row: dict) -> tuple[float, float] | None:
    home = row.get("home_regulation_goals", row.get("home_mean"))
    away = row.get("away_regulation_goals", row.get("away_mean"))
    if home is None or away is None:
        return None
    return float(home), float(away)


def _side_probability(paths, quote: dict) -> float | None:
    market = str(quote.get("market") or "MONEYLINE").upper()
    side = str(quote.get("side") or "").upper()
    if market in {"MONEYLINE", "ML", "H2H"}:
        mass = home_moneyline(paths)
        if side == "HOME":
            return mass.win
        if side == "AWAY":
            return mass.loss
        return None
    if market in {"PUCK_LINE", "PUCKLINE", "SPREAD", "PL"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"HOME", "AWAY"}:
            return None
        # Intake stores the home puck line. Away is the opposite number.
        home_line = float(line) if side == "HOME" else -float(line)
        mass = home_puck_line(paths, home_line if side == "HOME" else -float(line))
        return mass.win if side == "HOME" else home_puck_line(paths, -float(line)).win
    if market in {"TOTAL", "TOTALS"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"OVER", "UNDER"}:
            return None
        mass = game_total_over(paths, float(line))
        return mass.win if side == "OVER" else mass.loss
    return None


def _attach_baseline(rows: list, history_path: str | None) -> tuple[list, list]:
    if not history_path:
        return rows, []
    from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame
    from sportsedge.sports.nhl.public_baseline import (
        artifact_from_json_dict,
        build_baseline_matchup,
        game_state_from_public_baseline,
    )
    failures = []
    try:
        payload = json.loads(Path(history_path).read_text(encoding="utf-8"))
        artifact = artifact_from_json_dict(payload["artifact"])
        games = [NHLOfficialCompletedGame(**row) for row in payload["games"]]
    except Exception as exc:
        return rows, [{"stage": "BASELINE", "reason": f"{type(exc).__name__}: {exc}"}]
    built = []
    for row in rows:
        if _rates(row) is not None:
            built.append(row)
            continue
        try:
            matchup = build_baseline_matchup(
                games,
                game_id=str(row.get("game_id") or f"{row.get('away')}@{row.get('home')}"),
                home_team_id=str(row["home_team_id"]),
                away_team_id=str(row["away_team_id"]),
                puck_drop=str(row["puck_drop"]),
            )
            state = game_state_from_public_baseline(matchup, artifact)
            copied = dict(row)
            copied["home_regulation_goals"] = state.home_regulation_goals
            copied["away_regulation_goals"] = state.away_regulation_goals
            built.append(copied)
        except Exception as exc:
            failures.append({"stage": "BASELINE", "reason": f"{type(exc).__name__}: {exc}"})
            built.append(row)
    return built, failures


def build_card(rows: list, *, source_failures: list | None = None, simulations: int = 4000) -> dict:
    results = []
    quote_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        quotes = _quotes_for(row)
        quote_rows += len(quotes)
        rates = _rates(row)
        paths = None
        score_error = None
        if rates is not None:
            try:
                state = NHLGameState(
                    game_id=str(row.get("game_id") or f"{row.get('away')}@{row.get('home')}"),
                    home_regulation_goals=rates[0],
                    away_regulation_goals=rates[1],
                    home_ot_win_probability=float(row.get("home_ot_win_probability") or 0.5),
                )
                paths = simulate_game_paths(state, simulations=simulations)
            except Exception as exc:
                score_error = f"{type(exc).__name__}: {exc}"
        if not quotes:
            results.append({
                "game_id": row.get("game_id"),
                "home_team": row.get("home") or row.get("home_team"),
                "away_team": row.get("away") or row.get("away_team"),
                "model_p": None,
                "edge": None,
                "bet_status": "NO_BET",
                "reason": "NO_QUOTES",
                "score_error": score_error,
            })
            continue
        for quote in quotes:
            model_p = quote.get("model_p")
            if model_p is None and paths is not None and score_error is None:
                try:
                    model_p = _side_probability(paths, quote)
                except Exception as exc:
                    score_error = f"{type(exc).__name__}: {exc}"
                    model_p = None
            odds = quote.get("american_odds")
            edge = None
            if model_p is not None and odds is not None:
                edge = float(model_p) - _american_implied(float(odds))
            is_bet = model_p is not None and edge is not None and edge > 0
            results.append({
                "game_id": row.get("game_id") or quote.get("game_id"),
                "home_team": row.get("home") or row.get("home_team"),
                "away_team": row.get("away") or row.get("away_team"),
                "market": quote.get("market") or "MONEYLINE",
                "side": quote.get("side"),
                "line": quote.get("line", quote.get("point")),
                "american_odds": odds,
                "model_p": None if model_p is None else float(model_p),
                "edge": edge,
                "bet_status": "BET" if is_bet else "NO_BET",
                "reason": "EDGE_POSITIVE" if is_bet else ("NO_EDGE" if model_p is not None else (score_error or "MODEL_P_UNAVAILABLE")),
                "score_error": score_error,
            })
    bets = [row for row in results if row.get("bet_status") == "BET"]
    blocked = quote_rows == 0
    return {
        "schema_version": "NHL_LIVE_CARD_V1",
        "sport": "NHL",
        "status": "BLOCKED_NO_ODDS" if blocked else "SUCCESS",
        "run_status": "BLOCKED_NO_ODDS" if blocked else "READY",
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
        "results": results,
        "bets": bets,
        "source_failures": list(source_failures or []),
        "funnel": {
            "odds_rows_fetched": quote_rows,
            "model_priced": sum(row.get("model_p") is not None for row in results),
            "edge_positive": len(bets),
            "bets_emitted": len(bets),
            "pipeline_health": "BROKEN" if blocked else "OK",
            "pipeline_health_reason": "NO_ODDS_ROWS_REACHED_PRICING" if blocked else "QUOTES_PRICED",
        },
        "governance": {
            "sportsbook_api_used": False,
            "manual_market_board_required": True,
            "odds_api_called": False,
            "truth_gate_changed": False,
            "promotion_changed": False,
            "official_model_p": False,
            "lines_invented": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/live_nhl_card.json")
    parser.add_argument("--board-json")
    parser.add_argument("--history")
    parser.add_argument("--simulations", type=int, default=4000)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        board = _load_board(args.board_json or os.environ.get("NHL_MANUAL_BOARD_JSON"))
        rows, failures = _attach_baseline(board, args.history or os.environ.get("NHL_BASELINE_HISTORY"))
        payload = build_card(rows, source_failures=failures, simulations=int(args.simulations))
    except Exception as exc:
        payload = {
            "schema_version": "NHL_LIVE_CARD_V1",
            "sport": "NHL",
            "status": "BLOCKED_NO_ODDS",
            "run_status": "BLOCKED_NO_ODDS",
            "results": [],
            "bets": [],
            "source_failures": [{"reason": f"{type(exc).__name__}: {exc}"}],
            "funnel": {"odds_rows_fetched": 0, "model_priced": 0, "edge_positive": 0, "bets_emitted": 0, "pipeline_health": "BROKEN", "pipeline_health_reason": "RUNNER_EXCEPTION"},
            "governance": {"sportsbook_api_used": False, "manual_market_board_required": True, "odds_api_called": False, "official_model_p": False, "lines_invented": False},
        }
    payload["generated_at_utc"] = now.isoformat()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "bets": payload["funnel"]["bets_emitted"], "quotes": payload["funnel"]["odds_rows_fetched"], "output": str(out)}, sort_keys=True))
    return 2 if payload["funnel"]["odds_rows_fetched"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
