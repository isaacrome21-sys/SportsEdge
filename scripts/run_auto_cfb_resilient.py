#!/usr/bin/env python3
"""CFB card runner shaped like scripts/run_auto_mlb_resilient.py.

User-supplied lines only. No Odds API. A row with model_p and positive edge is a
bet. A no-edge slate is success. Zero quotes is the only infrastructure block.

Binds bakeoff 37093707442 PRIOR_CURRENT_BLEND (ridge alpha 300, joint RMSE 12.018)
without changing freeze status. Freeze stays UNFROZEN while artifact_sha256 is null.
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

from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit, score_selected_game

BAKEOFF_RUN = 37093707442
FAMILY = "PRIOR_CURRENT_BLEND"
RIDGE_ALPHA = 300.0
RESIDUAL_SIGMA = 12.018
MARKET_KEYS = ("quotes", "american_odds", "odds", "price", "spread", "spread_line", "total", "total_line")


def _american_implied(odds: float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 100.0 / (odds + 100.0)


def _phi(z: float) -> float:
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def _moneyline_p(home: float, away: float) -> float:
    from math import sqrt
    return _phi((home - away) / (RESIDUAL_SIGMA * sqrt(2.0)))


def _side_probability(home: float, away: float, quote: dict) -> float | None:
    market = str(quote.get("market") or "MONEYLINE").upper()
    side = str(quote.get("side") or "").upper()
    margin = home - away
    total = home + away
    if market in {"MONEYLINE", "ML", "H2H"}:
        if side == "HOME":
            return _moneyline_p(home, away)
        if side == "AWAY":
            return 1.0 - _moneyline_p(home, away)
        return None
    if market == "SPREAD":
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"HOME", "AWAY"}:
            return None
        # Manual screenshot quotes carry the selected side's line, not a shared home line.
        # HOME -3.5 and AWAY +3.5 are complementary at the same matchup.
        return _phi(((margin if side == "HOME" else -margin) + float(line)) / RESIDUAL_SIGMA)
    if market in {"TOTAL", "TOTALS"}:
        line = quote.get("line", quote.get("point"))
        if line is None or side not in {"OVER", "UNDER"}:
            return None
        over = _phi((total - float(line)) / RESIDUAL_SIGMA)
        return over if side == "OVER" else 1.0 - over
    return None


def _score_row(model, row: dict) -> tuple[float, float]:
    blind = {key: value for key, value in row.items() if key not in MARKET_KEYS}
    return score_selected_game(model, blind)


def _load_board(raw: str | None) -> list:
    text = str(raw or "").strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("events") or payload.get("rows") or payload.get("board") or []
    if not isinstance(payload, list):
        raise ValueError("CFB_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    return payload


def _quote_count(rows: list) -> int:
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        quotes = row.get("quotes")
        if isinstance(quotes, list) and quotes:
            count += len(quotes)
        elif row.get("american_odds") is not None:
            count += 1
    return count


def _group_manual_quotes(rows: list, *, games: list, alias_index: dict) -> dict[str, list]:
    """Bind user-entered DK quotes to CFBD games without using any sportsbook API.

    Each spread quote's line applies to its OWN side (HOME -3.5, AWAY +3.5).
    Unknown teams or malformed quotes fail closed instead of silently yielding
    an empty card.  The previous adapter incorrectly expected Odds API-shaped
    events with nested bookmakers rather than the documented manual board.
    """
    from sportsedge.sports.cfb.source import bind_provider_team

    by_matchup = {(g.home_team, g.away_team): g for g in games}
    grouped: dict[str, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CFB_AUTO_BOARD_GAME_NOT_OBJECT")
        home = bind_provider_team(str(row.get("home_team") or row.get("home") or ""), alias_index)
        away = bind_provider_team(str(row.get("away_team") or row.get("away") or ""), alias_index)
        game = by_matchup.get((home, away))
        if game is None:
            raise ValueError(f"CFB_AUTO_MATCHUP_UNRESOLVED:{away}@{home}")
        raw_quotes = row.get("quotes")
        if not isinstance(raw_quotes, list):
            raw_quotes = [row] if row.get("american_odds") is not None else []
        if not raw_quotes:
            raise ValueError(f"CFB_AUTO_GAME_HAS_NO_QUOTES:{away}@{home}")
        for quote in raw_quotes:
            if not isinstance(quote, dict):
                raise ValueError("CFB_AUTO_QUOTE_NOT_OBJECT")
            market = str(quote.get("market") or "").upper()
            market = {"ML": "MONEYLINE", "H2H": "MONEYLINE", "TOTALS": "TOTAL"}.get(market, market)
            side = str(quote.get("side") or "").upper()
            allowed = {"SPREAD": {"HOME", "AWAY"}, "TOTAL": {"OVER", "UNDER"},
                       "MONEYLINE": {"HOME", "AWAY"}}
            if market not in allowed or side not in allowed[market]:
                raise ValueError(f"CFB_AUTO_MARKET_SIDE_INVALID:{market}/{side}")
            odds = quote.get("american_odds")
            if odds is None:
                raise ValueError("CFB_AUTO_AMERICAN_ODDS_REQUIRED")
            odds = float(odds)
            if -100 < odds < 100:
                raise ValueError("CFB_AUTO_INVALID_AMERICAN_ODDS")
            line = quote.get("line", quote.get("point"))
            if market != "MONEYLINE" and line is None:
                raise ValueError(f"CFB_AUTO_LINE_REQUIRED:{market}")
            grouped.setdefault(game.game_id, []).append({
                "game_id": game.game_id, "market": market, "side": side,
                "line": 0.0 if market == "MONEYLINE" else float(line),
                "american_odds": odds, "book_key": "draftkings",
                "sportsbook": "DraftKings",
            })
    return grouped


def _attach_live(rows: list, *, season: int | None, week: int | None, asof: str | None) -> tuple[list, list]:
    """Attach CFBD dual snapshots when the board is not already training-shaped. No Odds API."""
    if rows and all(isinstance(row, dict) and row.get("home_prior_metrics") and row.get("home_current_metrics") for row in rows):
        return rows, []
    from sportsedge.sports.cfb.candidate_live_source import (
        attach_candidate_snapshots_to_game_row,
        fetch_cfbd_candidate_metric_snapshots,
    )
    from sportsedge.sports.cfb.source import (
        attach_weather,
        build_team_alias_index,
        fetch_cfbd_games,
        fetch_cfbd_teams,
        fetch_cfbd_weather,
    )
    key = str(os.environ.get("SPORTSEDGE_CFBD_API_KEY") or os.environ.get("CFBD_API_KEY") or "").strip()
    failures = []
    if not key:
        failures.append({"stage": "CFBD", "reason": "CFB_AUTO_CFBD_API_KEY_REQUIRED"})
        return rows, failures
    now = datetime.fromisoformat(asof.replace("Z", "+00:00")) if asof else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    season_i = int(season if season is not None else now.year)
    try:
        if week is None:
            from sportsedge.sports.cfb.auto_slate import discover_cfb_auto_games
            plan = discover_cfb_auto_games(as_of=now, cfbd_api_key=key, season=season_i, min_lead_minutes=0, horizon_minutes=16 * 7 * 24 * 60)
            future = []
            for game in plan.get("games") or []:
                kick = str(game.get("kickoff_ts") or "")
                if kick and datetime.fromisoformat(kick.replace("Z", "+00:00")) > now:
                    future.append((kick, int(game.get("week"))))
            if not future:
                raise RuntimeError("CFB_AUTO_NO_FUTURE_FBS_WEEK")
            week_i = sorted(future)[0][1]
        else:
            week_i = int(week)
        team_rows = fetch_cfbd_teams(season=season_i, cfbd_api_key=key)
        games = attach_weather(
            fetch_cfbd_games(season=season_i, week=week_i, cfbd_api_key=key),
            fetch_cfbd_weather(season=season_i, week=week_i, cfbd_api_key=key),
        )
        by_game = _group_manual_quotes(
            rows, games=games, alias_index=build_team_alias_index(team_rows),
        )
        snaps = fetch_cfbd_candidate_metric_snapshots(season=season_i, week=week_i, cfbd_api_key=key, now=now)
    except Exception as exc:
        failures.append({"stage": "CFBD", "reason": f"{type(exc).__name__}: {exc}"})
        return rows, failures
    game_map = {game.game_id: game for game in games}
    built = []
    for game_id, quote_rows in by_game.items():
        game = game_map[game_id]
        base = {
            "game_id": game.game_id,
            "neutral_site": bool(game.neutral_site),
            "weather": dict(game.weather or {}),
            "home_team": game.home_team,
            "away_team": game.away_team,
        }
        try:
            attached = attach_candidate_snapshots_to_game_row(
                base,
                home_team=game.home_team,
                away_team=game.away_team,
                snapshots=snaps,
            )
        except Exception as exc:
            failures.append({"stage": "SNAPSHOT", "reason": f"{game_id}:{type(exc).__name__}: {exc}"})
            attached = base
        attached["quotes"] = quote_rows
        built.append(attached)
    return built, failures


def build_card(rows: list, *, model, source_failures: list | None = None) -> dict:
    results = []
    quote_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        quotes = list(row.get("quotes") or [])
        if not quotes and row.get("american_odds") is not None:
            quotes = [row]
        quote_rows += len(quotes)
        home = away = None
        score_error = None
        if row.get("home_prior_metrics") and row.get("home_current_metrics"):
            try:
                home, away = _score_row(model, row)
            except Exception as exc:
                score_error = f"{type(exc).__name__}: {exc}"
        if not quotes:
            results.append({
                "game_id": row.get("game_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "home_mean": home,
                "away_mean": away,
                "model_p": None,
                "edge": None,
                "bet_status": "NO_BET",
                "reason": "NO_QUOTES",
                "score_error": score_error,
            })
            continue
        for quote in quotes:
            model_p = None
            if home is not None and away is not None and score_error is None:
                try:
                    model_p = _side_probability(home, away, quote)
                except Exception as exc:
                    score_error = f"{type(exc).__name__}: {exc}"
            odds = quote.get("american_odds")
            edge = None
            if model_p is not None and odds is not None:
                edge = float(model_p) - _american_implied(float(odds))
            is_bet = model_p is not None and edge is not None and edge > 0
            results.append({
                "game_id": row.get("game_id") or quote.get("game_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "market": quote.get("market") or "MONEYLINE",
                "side": quote.get("side"),
                "line": quote.get("line", quote.get("point")),
                "american_odds": odds,
                "home_mean": home,
                "away_mean": away,
                "model_p": model_p,
                "edge": edge,
                "bet_status": "BET" if is_bet else "NO_BET",
                "reason": "EDGE_POSITIVE" if is_bet else ("NO_EDGE" if model_p is not None else (score_error or "MODEL_P_UNAVAILABLE")),
                "score_error": score_error,
            })
    bets = [row for row in results if row.get("bet_status") == "BET"]
    blocked = quote_rows == 0
    unpriced = not blocked and not any(row.get("model_p") is not None for row in results)
    run_status = "BLOCKED_NO_ODDS" if blocked else "BLOCKED_MODEL_UNAVAILABLE" if unpriced else "READY"
    return {
        "schema_version": "CFB_LIVE_CARD_V1",
        "status": "SUCCESS" if run_status == "READY" else run_status,
        "run_status": run_status,
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
        "family": FAMILY,
        "ridge_alpha": RIDGE_ALPHA,
        "residual_sigma": RESIDUAL_SIGMA,
        "bakeoff_run": BAKEOFF_RUN,
        "results": results,
        "bets": bets,
        "source_failures": list(source_failures or []),
        "funnel": {
            "odds_rows_fetched": quote_rows,
            "model_priced": sum(row.get("model_p") is not None for row in results),
            "edge_positive": len(bets),
            "bets_emitted": len(bets),
            "pipeline_health": "BROKEN" if blocked or unpriced else "OK",
            "pipeline_health_reason": (
                "NO_ODDS_ROWS_REACHED_PRICING" if blocked
                else "CFB_AUTO_NO_MODEL_PRICED" if unpriced else "OK"
            ),
        },
        "governance": {
            "sportsbook_api_used": False,
            "odds_api_called": False,
            "manual_market_board_required": True,
            "freeze_status": "UNFROZEN",
            "artifact_sha256": None,
            "promotion_authority": False,
            "truth_gate": False,
            "official_model_p": False,
            "blocker": "CFB_RECONSTRUCTED_TRAINING_AND_SELECTION_NOT_COMPLETE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/live_cfb_card.json")
    parser.add_argument("--board-json", default="")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--asof")
    parser.add_argument("--fit", default=str(ROOT / "config/cfb_sdv_prior_current_blend_fit_v1.json"))
    args = parser.parse_args()
    raw = args.board_json or os.environ.get("CFB_MANUAL_BOARD_JSON") or ""
    try:
        rows = _load_board(raw)
    except Exception as exc:
        payload = build_card([], model=None, source_failures=[{"stage": "BOARD", "reason": f"{type(exc).__name__}: {exc}"}])
        payload["run_status"] = "BLOCKED_NO_ODDS"
        payload["status"] = "BLOCKED_NO_ODDS"
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 2
    if _quote_count(rows) == 0:
        model = load_selected_sdv_fit(args.fit)
        payload = build_card(rows, model=model, source_failures=[{"stage": "FUNNEL", "reason": "NO_ODDS_ROWS_REACHED_PRICING"}])
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_status": payload["run_status"], "bets": 0, "quotes": 0}))
        return 2
    model = load_selected_sdv_fit(args.fit)
    rows, failures = _attach_live(rows, season=args.season, week=args.week, asof=args.asof)
    payload = build_card(rows, model=model, source_failures=failures)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_status": payload["run_status"], "bets": payload["funnel"]["bets_emitted"], "quotes": payload["funnel"]["odds_rows_fetched"], "output": args.output}))
    return 0 if payload["run_status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
