#!/usr/bin/env python3
"""NHL card runner shaped like scripts/run_auto_mlb_resilient.py.

User-supplied lines only. No Odds API. Prices sides from the existing rate v1
final-score distribution. A row with model_p and positive edge is a bet. A
no-edge slate is success. Zero quotes is the only infrastructure block.

Does not invent lines, does not set a freeze FROZEN, and does not restore
Truth Gate or official Model_P.
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

from sportsedge.nhl_rate_v1_card import (
    final_score_distribution,
    no_vig,
    puck_line_probs,
    resolve_team,
    total_probs,
)

FAMILY = "NHL_RATE_V1"
PRICED_MARKETS = {"MONEYLINE", "ML", "H2H", "PUCK_LINE", "PUCKLINE", "SPREAD", "TOTAL", "TOTALS"}


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
        payload = payload.get("events") or payload.get("rows") or payload.get("games") or payload.get("board") or []
    if not isinstance(payload, list):
        raise ValueError("NHL_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
    return payload


def _flatten(rows: list) -> list[dict]:
    flat = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        quotes = row.get("quotes")
        markets = row.get("markets")
        if isinstance(quotes, list) and quotes:
            for quote in quotes:
                if isinstance(quote, dict):
                    merged = {**row, **quote}
                    merged.pop("quotes", None)
                    merged.pop("markets", None)
                    flat.append(merged)
            continue
        if isinstance(markets, list) and markets:
            for market in markets:
                if not isinstance(market, dict):
                    continue
                base = {key: value for key, value in row.items() if key != "markets"}
                name = str(market.get("market") or "MONEYLINE").upper()
                line = market.get("line")
                away_price = market.get("away_or_over_price", market.get("away_odds"))
                home_price = market.get("home_or_under_price", market.get("home_odds"))
                if name in {"TOTAL", "TOTALS"}:
                    if away_price is not None:
                        flat.append({**base, "market": "TOTAL", "side": "OVER", "line": line, "american_odds": away_price})
                    if home_price is not None:
                        flat.append({**base, "market": "TOTAL", "side": "UNDER", "line": line, "american_odds": home_price})
                else:
                    side_name = "PUCK_LINE" if name in {"PUCK_LINE", "PUCKLINE", "SPREAD"} else "MONEYLINE"
                    if away_price is not None:
                        flat.append({**base, "market": side_name, "side": "AWAY", "line": line, "american_odds": away_price})
                    if home_price is not None:
                        flat.append({**base, "market": side_name, "side": "HOME", "line": line, "american_odds": home_price})
            continue
        flat.append(row)
    return flat


def _quote_count(rows: list[dict]) -> int:
    return sum(1 for row in rows if row.get("american_odds") is not None or row.get("odds") is not None or row.get("price") is not None)


def _odds(row: dict) -> float | None:
    for key in ("american_odds", "odds", "price"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def _pair_market(rows: list[dict]) -> dict[tuple, tuple[float, float]]:
    grouped: dict[tuple, dict[str, float]] = {}
    for row in rows:
        odds = _odds(row)
        if odds is None:
            continue
        key = (
            str(row.get("game_id") or f"{row.get('away')}@{row.get('home')}"),
            str(row.get("market") or "").upper(),
            row.get("line"),
        )
        grouped.setdefault(key, {})[str(row.get("side") or "").upper()] = odds
    out = {}
    for key, sides in grouped.items():
        if "HOME" in sides and "AWAY" in sides:
            out[key] = no_vig(int(sides["AWAY"]), int(sides["HOME"]))
        elif "OVER" in sides and "UNDER" in sides:
            out[key] = no_vig(int(sides["OVER"]), int(sides["UNDER"]))
    return out


def _score(row: dict) -> tuple[float | None, float | None, str]:
    away = resolve_team(str(row.get("away") or row.get("away_team") or ""))
    home = resolve_team(str(row.get("home") or row.get("home_team") or ""))
    market = str(row.get("market") or "MONEYLINE").upper()
    side = str(row.get("side") or "").upper()
    if market not in PRICED_MARKETS:
        return None, None, "NO_MODEL"
    if not away or not home:
        return None, None, "TEAM_UNRESOLVED"
    fsd = final_score_distribution(away, home)
    if fsd is None:
        return None, None, "NO_MODEL:TEAM_PRIOR_MISSING"
    if market in {"MONEYLINE", "ML", "H2H"}:
        home_p = sum(p for (hg, ag), p in fsd["dist"].items() if hg > ag)
        if side == "HOME":
            return home_p, 0.0, "NHL_RATE_V1"
        if side == "AWAY":
            return 1.0 - home_p, 0.0, "NHL_RATE_V1"
        return None, None, "SIDE_REQUIRED"
    line = row.get("line", row.get("point"))
    if line is None:
        return None, None, "LINE_MISSING"
    if market in {"PUCK_LINE", "PUCKLINE", "SPREAD"}:
        away_line = float(line) if side == "AWAY" else -float(line)
        away_p, push, home_p = puck_line_probs(fsd, away_line)
        if side == "AWAY":
            return away_p / max(1e-9, 1.0 - push), push, "NHL_RATE_V1"
        if side == "HOME":
            return home_p / max(1e-9, 1.0 - push), push, "NHL_RATE_V1"
        return None, None, "SIDE_REQUIRED"
    over, push, under = total_probs(fsd, float(line))
    if side == "OVER":
        return over / max(1e-9, 1.0 - push), push, "NHL_RATE_V1"
    if side == "UNDER":
        return under / max(1e-9, 1.0 - push), push, "NHL_RATE_V1"
    return None, None, "SIDE_REQUIRED"


def build_card(rows: list[dict], source_failures: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    pairs = _pair_market(rows)
    results = []
    for row in rows:
        odds = _odds(row)
        model_p, push_p, reason = _score(row)
        key = (
            str(row.get("game_id") or f"{row.get('away')}@{row.get('home')}"),
            str(row.get("market") or "").upper(),
            row.get("line"),
        )
        side = str(row.get("side") or "").upper()
        if odds is None:
            market_p = None
        elif key in pairs:
            away_fair, home_fair = pairs[key]
            if side in {"AWAY", "OVER"}:
                market_p = away_fair
            else:
                market_p = home_fair
        else:
            market_p = _american_implied(odds)
        edge = None if model_p is None or market_p is None else model_p - market_p
        bet = model_p is not None and edge is not None and edge > 0
        results.append({
            "game_id": row.get("game_id") or f"{row.get('away')}@{row.get('home')}",
            "away": row.get("away") or row.get("away_team"),
            "home": row.get("home") or row.get("home_team"),
            "market": str(row.get("market") or "MONEYLINE").upper(),
            "side": side,
            "line": row.get("line"),
            "american_odds": odds,
            "model_p": model_p,
            "push_p": push_p,
            "market_p": market_p,
            "edge": edge,
            "bet_status": "BET" if bet else ("NO_EDGE" if model_p is not None else "UNPRICED"),
            "reason": reason if model_p is not None else reason,
            "family": FAMILY,
        })
    quotes = _quote_count(rows)
    bets = [row for row in results if row["bet_status"] == "BET"]
    priced = sum(row["model_p"] is not None for row in results)
    blocked = quotes == 0
    return {
        "sport": "NHL",
        "family": FAMILY,
        "generated_at_utc": now.isoformat(),
        "run_status": "BLOCKED_NO_ODDS" if blocked else "OK",
        "odds_api_called": False,
        "manual_market_board_required": True,
        "truth_gate": False,
        "official_model_p": False,
        "promotion_authority": False,
        "results": results,
        "bets": bets,
        "source_failures": source_failures + ([{"stage": "FUNNEL", "reason": "NO_ODDS_ROWS_REACHED_PRICING"}] if blocked else []),
        "funnel": {
            "odds_rows_fetched": quotes,
            "model_priced": priced,
            "edge_positive": len(bets),
            "bets_emitted": len(bets),
            "blocked_rows": 0 if not blocked else len(results),
            "pipeline_health": "BROKEN" if blocked else "OK",
        },
        "summary": {
            "both_sides": True,
            "side_rows": sum(1 for row in results if row["market"] in {"MONEYLINE", "ML", "H2H", "PUCK_LINE", "PUCKLINE", "SPREAD"}),
            "total_rows": sum(1 for row in results if row["market"] in {"TOTAL", "TOTALS"}),
            "prop_rows": sum(1 for row in results if row["market"] not in PRICED_MARKETS),
            "catalog_complete": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/live_nhl_card.json")
    parser.add_argument("--board-json", default="")
    args = parser.parse_args()
    raw = args.board_json or os.environ.get("NHL_MANUAL_BOARD_JSON") or os.environ.get("SPORTSEDGE_NHL_BOARD") or ""
    try:
        rows = _flatten(_load_board(raw))
    except Exception as exc:
        payload = build_card([], [{"stage": "BOARD", "reason": f"{type(exc).__name__}: {exc}"}])
        payload["run_status"] = "BLOCKED_NO_ODDS"
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_status": payload["run_status"], "reason": str(exc)}))
        return 2
    payload = build_card(rows, [])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_status": payload["run_status"],
        "bets": payload["funnel"]["bets_emitted"],
        "quotes": payload["funnel"]["odds_rows_fetched"],
        "output": args.output,
    }))
    return 2 if payload["run_status"] == "BLOCKED_NO_ODDS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
