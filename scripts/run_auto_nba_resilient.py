#!/usr/bin/env python3
"""NBA card runner shaped like scripts/run_auto_mlb_resilient.py.

User-supplied lines only. No Odds API. Sides and totals get model_p and edge
from the existing ratings v1 margin/total (market-anchored blend already in
sportsedge.sports.nba.lines_card). A row with model_p and positive edge is a
bet. A no-edge slate is success. Zero quotes is the only infrastructure block.

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

from sportsedge.sports.nba.lines_card import (
    Game,
    Market,
    price_game,
    ratings_from_results,
    team_abbr,
)

FAMILY = "NBA_RATINGS_V1"
PRICED = {"MONEYLINE", "ML", "H2H", "SPREAD", "TOTAL", "TOTALS"}


def _load_board(raw: str | None) -> list:
    text = str(raw or "").strip()
    if not text:
        return []
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("events") or payload.get("rows") or payload.get("games") or payload.get("board") or []
    if not isinstance(payload, list):
        raise ValueError("NBA_AUTO_MANUAL_BOARD_ARRAY_REQUIRED")
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
                away_price = market.get("away_or_over_price", market.get("away_odds", market.get("p1")))
                home_price = market.get("home_or_under_price", market.get("home_odds", market.get("p2")))
                if name in {"TOTAL", "TOTALS"}:
                    if away_price is not None:
                        flat.append({**base, "market": "TOTAL", "side": "OVER", "line": line, "american_odds": away_price})
                    if home_price is not None:
                        flat.append({**base, "market": "TOTAL", "side": "UNDER", "line": line, "american_odds": home_price})
                else:
                    side_name = "SPREAD" if name in {"SPREAD", "PS"} else "MONEYLINE"
                    if away_price is not None:
                        flat.append({**base, "market": side_name, "side": "AWAY", "line": line, "american_odds": away_price})
                    if home_price is not None:
                        flat.append({**base, "market": side_name, "side": "HOME", "line": line, "american_odds": home_price})
            continue
        flat.append(row)
    return flat


def _odds(row: dict):
    for key in ("american_odds", "odds", "price"):
        if row.get(key) is not None:
            return int(float(row[key]))
    return None


def _quote_count(rows: list[dict]) -> int:
    return sum(1 for row in rows if _odds(row) is not None)


def _team(value) -> str | None:
    if not value:
        return None
    try:
        return team_abbr(str(value))
    except Exception:
        return None


class _FixedRatings:
    def __init__(self, margin: float, total: float):
        self.margin = float(margin)
        self.total = float(total)

    def margin_total(self, home: str, away: str, *, neutral: bool = False):
        return self.margin, self.total


def _ratings(path: str | None):
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    results = raw.get("results") if isinstance(raw, dict) else raw
    if not isinstance(results, list) or not results:
        return None
    return ratings_from_results(results)


def _group_games(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    groups: dict[str, tuple[dict, list[dict]]] = {}
    for row in rows:
        away = row.get("away") or row.get("away_team")
        home = row.get("home") or row.get("home_team")
        key = str(row.get("game_id") or f"{away}@{home}")
        groups.setdefault(key, (row, []))
        groups[key][1].append(row)
    return list(groups.values())


def _markets(quotes: list[dict]) -> list[Market]:
    paired: dict[tuple, dict] = {}
    for quote in quotes:
        market = str(quote.get("market") or "MONEYLINE").upper()
        if market in {"ML", "H2H"}:
            market = "MONEYLINE"
        if market in {"TOTALS"}:
            market = "TOTAL"
        if market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            continue
        side = str(quote.get("side") or "").upper()
        odds = _odds(quote)
        if odds is None or side not in {"HOME", "AWAY", "OVER", "UNDER"}:
            continue
        slot = paired.setdefault((market, quote.get("line")), {"line": quote.get("line"), "raw": quote.get("raw") or market})
        if side in {"AWAY", "OVER"}:
            slot["p1"] = odds
        else:
            slot["p2"] = odds
    markets = []
    for (market, line), slot in paired.items():
        if "p1" not in slot or "p2" not in slot:
            continue
        markets.append(Market(market, None if line is None else float(line), int(slot["p1"]), int(slot["p2"]), str(slot["raw"])))
    return markets


def build_card(rows: list[dict], *, ratings, source_failures: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    results = []
    for seed, quotes in _group_games(rows):
        away = _team(seed.get("away") or seed.get("away_team"))
        home = _team(seed.get("home") or seed.get("home_team"))
        markets = _markets(quotes)
        priced = {}
        reason = "NBA_RATINGS_V1"
        if away and home and markets:
            game = Game(away, home, f"{away} @ {home}", markets)
            model = ratings
            if seed.get("margin") is not None and seed.get("total") is not None:
                model = _FixedRatings(float(seed["margin"]), float(seed["total"]))
            elif seed.get("home_mean") is not None and seed.get("away_mean") is not None:
                home_mean = float(seed["home_mean"])
                away_mean = float(seed["away_mean"])
                model = _FixedRatings(home_mean - away_mean, home_mean + away_mean)
            if model is None:
                reason = "RATINGS_MISSING"
            else:
                try:
                    _margin, _total, priced_rows = price_game(game, model)
                    for row in priced_rows:
                        priced[(row.market, row.side, row.price)] = row
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
        elif not away or not home:
            reason = "TEAM_UNRESOLVED"
        for quote in quotes:
            odds = _odds(quote)
            market = str(quote.get("market") or "MONEYLINE").upper()
            if market in {"ML", "H2H"}:
                market = "MONEYLINE"
            if market == "TOTALS":
                market = "TOTAL"
            side = str(quote.get("side") or "").upper()
            label = None
            model_p = None
            market_p = None
            if side in {"AWAY", "OVER"}:
                label = f"{away} ML" if market == "MONEYLINE" else (
                    f"{away} {float(quote.get('line')):+g}" if market == "SPREAD" and quote.get("line") is not None else f"Over {float(quote.get('line')):g}" if quote.get("line") is not None else None
                )
            elif side in {"HOME", "UNDER"}:
                home_line = None if quote.get("line") is None else -float(quote.get("line"))
                label = f"{home} ML" if market == "MONEYLINE" else (
                    f"{home} {home_line:+g}" if market == "SPREAD" and home_line is not None else f"Under {float(quote.get('line')):g}" if quote.get("line") is not None else None
                )
            hit = priced.get((market, label, odds)) if label is not None and odds is not None else None
            if hit is not None:
                model_p = float(hit.model_p)
                market_p = float(hit.novig_p)
            edge = None if model_p is None or market_p is None else model_p - market_p
            bet = model_p is not None and edge is not None and edge > 0
            results.append({
                "game_id": seed.get("game_id") or f"{away}@{home}",
                "away": away or seed.get("away") or seed.get("away_team"),
                "home": home or seed.get("home") or seed.get("home_team"),
                "market": market,
                "side": side,
                "line": quote.get("line"),
                "american_odds": odds,
                "model_p": model_p,
                "market_p": market_p,
                "edge": edge,
                "bet_status": "BET" if bet else ("NO_BET" if model_p is not None else "UNPRICED"),
                "reason": "EDGE_POSITIVE" if bet else ("NO_EDGE" if model_p is not None else reason),
                "family": FAMILY,
                "official_eligible": False,
            })
    quotes = _quote_count(rows)
    bets = [row for row in results if row["bet_status"] == "BET"]
    blocked = quotes == 0
    return {
        "sport": "NBA",
        "schema_version": "NBA_LIVE_CARD_V1",
        "family": FAMILY,
        "generated_at_utc": now.isoformat(),
        "run_status": "BLOCKED_NO_ODDS" if blocked else "READY",
        "market_input_source": "MANUAL_SCREENSHOT_BOARD",
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
            "model_priced": sum(row.get("model_p") is not None for row in results),
            "edge_positive": len(bets),
            "bets_emitted": len(bets),
            "pipeline_health": "BROKEN" if blocked else "OK",
            "pipeline_health_reason": "NO_ODDS_ROWS_REACHED_PRICING" if blocked else "OK",
        },
        "summary": {
            "both_sides": True,
            "side_rows": sum(1 for row in results if row["market"] in {"MONEYLINE", "SPREAD"}),
            "total_rows": sum(1 for row in results if row["market"] == "TOTAL"),
            "prop_rows": sum(1 for row in results if row["market"] not in PRICED),
            "catalog_complete": True,
        },
        "governance": {
            "odds_api_called": False,
            "truth_gate": False,
            "official_model_p": False,
            "freeze_status": "UNFROZEN",
            "artifact_sha256": None,
            "promotion_authority": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/live_nba_card.json")
    parser.add_argument("--board-json", default="")
    parser.add_argument("--results", default="")
    args = parser.parse_args()
    raw = args.board_json or os.environ.get("NBA_MANUAL_BOARD_JSON") or os.environ.get("SPORTSEDGE_NBA_BOARD") or ""
    results_path = args.results or os.environ.get("SPORTSEDGE_NBA_RESULTS") or ""
    try:
        rows = _flatten(_load_board(raw))
        ratings = _ratings(results_path or None)
    except Exception as exc:
        payload = build_card([], ratings=None, source_failures=[{"stage": "BOARD", "reason": f"{type(exc).__name__}: {exc}"}])
        payload["run_status"] = "BLOCKED_NO_ODDS"
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_status": payload["run_status"], "reason": str(exc)}))
        return 2
    payload = build_card(rows, ratings=ratings, source_failures=[])
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
