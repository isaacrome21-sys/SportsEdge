#!/usr/bin/env python3
"""Price a manual DK CFB board with the bakeoff-selected PRIOR_CURRENT_BLEND fit.

Works like the MLB card: a quote is a BET when its edge against the
de-vigged price clears the 2% floor; one team-outcome bet per game
(best of moneyline/spread), totals judged separately. No sportsbook API.

Board JSON: a list of
  {"game_id": "<CFBD id>",
   "quotes": [{"market": "MONEYLINE", "side": "HOME"|"AWAY", "american_odds": -150},
              {"market": "SPREAD", "side": "HOME"|"AWAY", "line": -7.5, "american_odds": -110},
              {"market": "TOTAL", "side": "OVER"|"UNDER", "line": 52.5, "american_odds": -110}]}
SPREAD line is the handicap for the quoted side.

Compact phone form is also accepted (game_id optional, resolved by team name):
  {"away": "Michigan", "home": "Minnesota", "ml": [-225, 185],
   "spread": [-6, -110, -110], "total": [43.5, -105, -115]}
spread = [away line, away price, home price]; total = [line, over price, under price].
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from math import erf, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Bakeoff run 37093707442: per-team joint home/away score RMSE.
TEAM_SCORE_RMSE = 12.018
# Margin and total sigma assuming independent home/away residuals.
COMBINED_SIGMA = TEAM_SCORE_RMSE * sqrt(2.0)
EDGE_FLOOR = 0.02  # same floor as the MLB card (#1230)


def phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def implied(odds: float) -> float:
    return abs(odds) / (abs(odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def model_prob(market: str, side: str, line, home: float, away: float) -> float:
    margin, total = home - away, home + away
    if market == "MONEYLINE":
        p_home = phi(margin / COMBINED_SIGMA)
        return p_home if side == "HOME" else 1.0 - p_home
    if market == "SPREAD":
        m = margin if side == "HOME" else -margin
        return phi((m + float(line)) / COMBINED_SIGMA)
    if market == "TOTAL":
        p_over = 1.0 - phi((float(line) - total) / COMBINED_SIGMA)
        return p_over if side == "OVER" else 1.0 - p_over
    raise ValueError("CFB_SDV_MARKET_UNSUPPORTED:" + market)


def pair_key(market: str, side: str, line):
    if market == "MONEYLINE":
        return (market,)
    if market == "SPREAD":
        lv = float(line)
        return (market, lv if side == "HOME" else -lv)
    return (market, float(line))


def price_game(game_id, home: float, away: float, quotes: list) -> list:
    norm = []
    for q in quotes:
        market = str(q.get("market") or "MONEYLINE").upper()
        side = str(q.get("side") or "").upper()
        norm.append((market, side, q.get("line"), float(q["american_odds"])))
    groups = {}
    for market, side, line, odds in norm:
        groups.setdefault(pair_key(market, side, line), []).append(implied(odds))
    out = []
    for market, side, line, odds in norm:
        raw = implied(odds)
        grp = groups[pair_key(market, side, line)]
        fair = raw / sum(grp) if len(grp) == 2 else None
        p = model_prob(market, side, line, home, away)
        edge = p - (fair if fair is not None else raw)
        out.append({
            "game_id": game_id,
            "market": market,
            "side": side,
            "line": line,
            "american_odds": odds,
            "home_mean": round(home, 2),
            "away_mean": round(away, 2),
            "model_p": round(p, 4),
            "market_p": round(fair if fair is not None else raw, 4),
            "devig": "PAIRED_PROPORTIONAL" if fair is not None else "UNPAIRED_RAW_IMPLIED",
            "edge": round(edge, 4),
            "bet_status": "BET" if edge >= EDGE_FLOOR else "PASS",
            "reason": "EDGE_CLEARS_FLOOR" if edge >= EDGE_FLOOR else "BELOW_FLOOR",
        })
    # Same-game guard: one team-outcome bet (ML or spread) and one total per game.
    for fam in (("MONEYLINE", "SPREAD"), ("TOTAL",)):
        bets = [r for r in out if r["market"] in fam and r["bet_status"] == "BET"]
        bets.sort(key=lambda r: -r["edge"])
        for r in bets[1:]:
            r["bet_status"], r["reason"] = "PASS", "SAME_GAME_GUARD"
    return out


ALIASES = {
    "mississippi": "ole miss", "umass": "massachusetts", "miami oh": "miami (oh)",
    "uconn": "connecticut", "north dakota st": "north dakota state",
    "nc state": "nc state", "usf": "south florida", "fiu": "florida international",
}


def _n(name: str) -> str:
    import re
    t = re.sub(r"[^a-z0-9() ]", " ", str(name).lower())
    t = " ".join(t.split())
    return ALIASES.get(t, t)


def expand_compact(row: dict) -> dict:
    if "quotes" in row:
        return row
    q = []
    if row.get("ml"):
        a, h = row["ml"]
        q += [{"market": "MONEYLINE", "side": "AWAY", "american_odds": a},
              {"market": "MONEYLINE", "side": "HOME", "american_odds": h}]
    if row.get("spread"):
        line, a, h = row["spread"]
        q += [{"market": "SPREAD", "side": "AWAY", "line": float(line), "american_odds": a},
              {"market": "SPREAD", "side": "HOME", "line": -float(line), "american_odds": h}]
    if row.get("total"):
        line, o, u = row["total"]
        q += [{"market": "TOTAL", "side": "OVER", "line": float(line), "american_odds": o},
              {"market": "TOTAL", "side": "UNDER", "line": float(line), "american_odds": u}]
    out = dict(row)
    out["quotes"] = q
    return out


def resolve_game(row: dict, games: list):
    if row.get("game_id") is not None:
        hit = [g for g in games if str(g.game_id) == str(row["game_id"])]
    else:
        a, h = _n(row.get("away", "")), _n(row.get("home", ""))
        def m(want, have):
            have = _n(have)
            return have == want or have.replace("(", "").replace(")", "") == want.replace("(", "").replace(")", "")
        hit = [g for g in games if m(a, g.away_team) and m(h, g.home_team)]
        if not hit:  # neutral-site listings can flip home/away
            hit = [g for g in games if m(a, g.home_team) and m(h, g.away_team)]
    if len(hit) != 1:
        raise SystemExit(f"CFB_SDV_GAME_UNRESOLVED:{row.get('game_id') or (row.get('away'), row.get('home'))}:{len(hit)}")
    return hit[0]


def build_rows(board: list, season: int, week: int, asof):
    from sportsedge.sports.cfb.candidate_live_source import (
        attach_candidate_snapshots_to_game_row,
        fetch_cfbd_candidate_metric_snapshots,
    )
    from sportsedge.sports.cfb.source import attach_weather, fetch_cfbd_games, fetch_cfbd_weather

    key = os.environ.get("CFBD_API_KEY") or os.environ.get("SPORTSEDGE_CFBD_API_KEY") or ""
    if not key:
        raise SystemExit("CFB_SDV_CFBD_API_KEY_REQUIRED")
    now = datetime.fromisoformat(asof.replace("Z", "+00:00")) if asof else datetime.now(timezone.utc)
    def count_hits(games_):
        n = 0
        for r in board:
            try:
                resolve_game(expand_compact(r), games_)
                n += 1
            except SystemExit:
                pass
        return n

    raw_games = fetch_cfbd_games(season=season, week=week, cfbd_api_key=key)
    if count_hits(raw_games) == 0:
        best = (0, week, raw_games)
        for w in range(1, 17):
            if w == week:
                continue
            try:
                g = fetch_cfbd_games(season=season, week=w, cfbd_api_key=key)
            except Exception:
                continue
            h = count_hits(g)
            if h > best[0]:
                best = (h, w, g)
        if best[0] == 0:
            sample = [(g.away_team, g.home_team) for g in raw_games[:15]]
            print("CFB_SDV_WEEK_SEARCH_FAILED sample week", week, "games:", sample)
        else:
            print(f"WEEK_AUTO_CORRECTED {week} -> {best[1]} ({best[0]} games matched)")
            week, raw_games = best[1], best[2]
    try:
        weather = fetch_cfbd_weather(season=season, week=week, cfbd_api_key=key)
    except Exception as exc:  # CFBD weather is a paid tier; free keys get 401
        print("WEATHER_NEUTRAL_FALLBACK", type(exc).__name__, str(exc)[:120])
        weather = {}
    # Missing weather -> training-mean wind/temp, outdoor: zero standardized weather effect.
    neutral = {"game_indoor": False, "wind_speed": 6.89, "temperature": 64.6, "fallback": "TRAINING_MEAN"}
    games = attach_weather(raw_games, {g.game_id: weather.get(g.game_id) or neutral for g in raw_games})
    snaps = fetch_cfbd_candidate_metric_snapshots(season=season, week=week, cfbd_api_key=key, now=now)
    try:
        print("SNAPSHOTS", len(snaps), "sample:", list(snaps)[:3] if not isinstance(snaps, dict) else list(snaps.keys())[:3])
    except Exception:
        pass
    rows = []
    unresolved = []
    for row in board:
        row = expand_compact(row)
        try:
            game = resolve_game(row, games)
        except SystemExit as exc:
            unresolved.append(str(exc))
            continue
        base = {
            "game_id": game.game_id,
            "home_team": game.home_team,
            "away_team": game.away_team,
            "neutral_site": bool(game.neutral_site),
            "weather": dict(game.weather or {}),
            "quotes": row.get("quotes") or [],
        }
        try:
            rows.append(attach_candidate_snapshots_to_game_row(
                base, home_team=game.home_team, away_team=game.away_team, snapshots=snaps))
        except Exception as exc:  # e.g. FCS opponent with no CFBD advanced stats
            unresolved.append(f"CFB_SDV_SNAPSHOT_MISSING:{game.away_team} @ {game.home_team}:{exc}")
    for u in unresolved:
        print("SKIPPED", u)
    if not rows:
        raise SystemExit("CFB_SDV_NO_GAMES_RESOLVED")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board-json", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--asof")
    ap.add_argument("--fit", type=Path, default=ROOT / "config/cfb_sdv_prior_current_blend_fit_v1.json")
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_sdv_card.json"))
    args = ap.parse_args()

    from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit, score_selected_game

    board = json.loads(args.board_json)
    if not isinstance(board, list) or not board:
        raise SystemExit("CFB_SDV_BOARD_ARRAY_REQUIRED")
    model = load_selected_sdv_fit(args.fit)
    results = []
    for row in build_rows(board, args.season, args.week, args.asof):
        try:
            home, away = score_selected_game(model, row)
        except Exception as exc:
            print("SKIPPED CFB_SDV_SCORE_FAILED", row.get("away_team"), "@", row.get("home_team"), exc)
            continue
        priced = price_game(row["game_id"], home, away, row.get("quotes") or [])
        for r in priced:
            r["matchup"] = f"{row.get('away_team')} @ {row.get('home_team')}"
        results.extend(priced or [{"game_id": row["game_id"], "bet_status": "PASS", "reason": "NO_QUOTES"}])
    payload = {
        "schema": "CFB_SDV_CARD_V2",
        "family": "PRIOR_CURRENT_BLEND",
        "bakeoff_run": 37093707442,
        "team_score_rmse": TEAM_SCORE_RMSE,
        "combined_sigma": round(COMBINED_SIGMA, 4),
        "edge_floor": EDGE_FLOOR,
        "sportsbook_api_used": False,
        "bets": sum(r.get("bet_status") == "BET" for r in results),
        "results": sorted(results, key=lambda r: -(r.get("edge") or -9)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for r in payload["results"]:
        if "edge" in r:
            print(f"{r['bet_status']:4s} {r['matchup']:45s} {r['market']:9s} {r['side']:5s} {str(r['line'] or ''):6s} "
                  f"{r['american_odds']:+6.0f}  model {r['model_p']:.3f}  mkt {r['market_p']:.3f}  edge {r['edge']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
