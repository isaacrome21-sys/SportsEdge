#!/usr/bin/env python3
"""PAPER slate from public results + DraftKings. Not official."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.draftkings_game_market_source import fetch_board, normalize_board

NFLVERSE = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
ESPN_CFB = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={date}&limit=300"
UA = {"User-Agent": "SportsEdge-PaperEngine/1", "Accept": "application/json,text/csv"}
SPORTS = {
    "americanfootball_nfl": {"hfa": 2.2, "sigma_margin": 13.5},
    "americanfootball_ncaaf": {"hfa": 2.8, "sigma_margin": 16.5},
    "baseball_mlb": {"hfa": 0.15, "sigma_margin": 3.2},
}


def _get(url: str) -> bytes:
    req = Request(url, headers=UA)
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def _american_to_prob(price: int) -> float:
    if price < 0:
        return (-price) / ((-price) + 100.0)
    return 100.0 / (price + 100.0)


def _devig(p_a: float, p_b: float) -> tuple[float, float]:
    s = p_a + p_b
    if s <= 0:
        return 0.5, 0.5
    return p_a / s, p_b / s


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def recency_mean(values: list[float], decay: float = 0.85, cap: int = 10) -> float | None:
    if len(values) < 3:
        return None
    use = values[-cap:]
    weights = [decay ** (len(use) - 1 - i) for i in range(len(use))]
    return sum(v * w for v, w in zip(use, weights)) / sum(weights)


def _pack(by_team: dict[str, list[tuple[str, float, float]]], cap: int = 10) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for team, games in by_team.items():
        games.sort()
        pf = recency_mean([g[1] for g in games], cap=cap)
        pa = recency_mean([g[2] for g in games], cap=cap)
        if pf is None or pa is None:
            continue
        out[team] = {"pf": pf, "pa": pa, "net": pf - pa, "n": float(len(games))}
    return out


def nfl_ratings() -> dict[str, dict[str, float]]:
    raw = _get(NFLVERSE).decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    by_team: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for row in rows:
        if str(row.get("game_type") or "REG") not in {"REG", "WC", "DIV", "CON", "SB"}:
            continue
        if str(row.get("season") or "") < "2024":
            continue
        try:
            hs, aws = float(row["home_score"]), float(row["away_score"])
        except (KeyError, TypeError, ValueError):
            continue
        day = str(row.get("gameday") or "")
        by_team[str(row.get("home_team"))].append((day, hs, aws))
        by_team[str(row.get("away_team"))].append((day, aws, hs))
    return _pack(by_team)


def espn_cfb_ratings(days: int = 28) -> dict[str, dict[str, float]]:
    teams: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    today = date.today()
    for offset in range(days):
        day = today - timedelta(days=offset)
        try:
            payload = json.loads(_get(ESPN_CFB.format(date=day.strftime("%Y%m%d"))))
        except Exception:
            continue
        for event in payload.get("events") or []:
            comp = (event.get("competitions") or [{}])[0]
            if str(comp.get("status", {}).get("type", {}).get("state")) != "post":
                continue
            parts = comp.get("competitors") or []
            if len(parts) != 2:
                continue
            try:
                scored = [(str(p["team"]["displayName"]), float(p["score"])) for p in parts]
            except (KeyError, TypeError, ValueError):
                continue
            a, b = scored
            when = str(event.get("date") or "")
            teams[a[0]].append((when, a[1], b[1]))
            teams[b[0]].append((when, b[1], a[1]))
    return _pack(teams, cap=8)


def match_team(name: str, ratings: dict[str, dict[str, float]]) -> str | None:
    if name in ratings:
        return name
    low = name.lower().strip()
    hits = [k for k in ratings if k.lower() == low or low in k.lower() or k.lower() in low]
    if len(hits) == 1:
        return hits[0]
    tail = name.split()[-1].lower() if name.split() else ""
    tails = [k for k in ratings if k.split()[-1].lower() == tail]
    return tails[0] if len(tails) == 1 else None


def predict(home: str, away: str, ratings: dict[str, dict[str, float]], hfa: float) -> dict[str, Any] | None:
    hk = match_team(home, ratings)
    ak = match_team(away, ratings)
    if not hk or not ak:
        return None
    h, a = ratings[hk], ratings[ak]
    home_pts = 0.5 * (h["pf"] + a["pa"]) + hfa / 2.0
    away_pts = 0.5 * (a["pf"] + h["pa"]) - hfa / 2.0
    return {
        "home_team_matched": hk,
        "away_team_matched": ak,
        "pred_home": round(home_pts, 2),
        "pred_away": round(away_pts, 2),
        "pred_margin": round(home_pts - away_pts, 2),
        "pred_total": round(home_pts + away_pts, 2),
    }


def group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (row["sport_key"], row["home_team"], row["away_team"], row["commence_time"])
        game = games.setdefault(key, {"quotes": {}})
        game.update({k: row[k] for k in ("sport_key", "home_team", "away_team", "commence_time")})
        game["quotes"].setdefault(row["market"], {})[row["outcome"]] = {
            "price_american": row["price_american"],
            "point": row.get("point"),
        }
    return list(games.values())


def priced_play(pred: dict[str, Any], game: dict[str, Any], sigma: float) -> dict[str, Any] | None:
    home = game["home_team"]
    book = (game.get("quotes") or {}).get("spreads") or {}
    if home not in book:
        return None
    line = book[home].get("point")
    price = book[home].get("price_american")
    if line is None or price is None:
        return None
    cover_p = _norm_cdf((pred["pred_margin"] + float(line)) / sigma)
    implied = _american_to_prob(int(price))
    other = [v for k, v in book.items() if k != home]
    if other and other[0].get("price_american") is not None:
        implied, _ = _devig(implied, _american_to_prob(int(other[0]["price_american"])))
    return {
        "market": "spreads",
        "side": home,
        "line": float(line),
        "price_american": int(price),
        "model_p": round(cover_p, 4),
        "book_fair_p": round(implied, 4),
        "edge_pp": round(100.0 * (cover_p - implied), 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="artifacts/paper_slate.json")
    args = parser.parse_args(argv)
    ratings = {
        "americanfootball_nfl": nfl_ratings(),
        "americanfootball_ncaaf": espn_cfb_ratings(),
        "baseball_mlb": {},
    }
    plays: list[dict[str, Any]] = []
    sport_status: dict[str, Any] = {}
    for sport, spec in SPORTS.items():
        try:
            rows = normalize_board(fetch_board(sport))
            sport_status[sport] = {"status": "OK", "normalized_rows": len(rows), "teams_rated": len(ratings[sport])}
        except Exception as exc:
            sport_status[sport] = {"status": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
            continue
        for game in group_rows(rows):
            card = {
                "sport_key": sport,
                "home_team": game["home_team"],
                "away_team": game["away_team"],
                "commence_time": game["commence_time"],
                "status": "PAPER_NOT_OFFICIAL",
                "official_authority": False,
                "model": "paper_recency_pfpa_v1",
                "reason": "UNFROZEN_PAPER_ENGINE",
            }
            pred = predict(game["home_team"], game["away_team"], ratings[sport], spec["hfa"])
            if pred is None:
                card["reason"] = "NO_RATING_MATCH"
                plays.append(card)
                continue
            card["prediction"] = pred
            priced = priced_play(pred, game, spec["sigma_margin"])
            if priced:
                card["priced"] = priced
                card["candidate"] = priced["edge_pp"] >= 3.0
            plays.append(card)
    report = {
        "contract": "SPORTSEDGE_PAPER_SLATE_V1",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "official_authority": False,
        "odds_api_used": False,
        "sports": sport_status,
        "plays": plays,
        "candidates": [p for p in plays if p.get("candidate")],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "wrote": str(out),
        "plays": len(plays),
        "candidates": len(report["candidates"]),
        "sports": {k: v.get("status") for k, v in sport_status.items()},
        "official_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
