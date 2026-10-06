#!/usr/bin/env python3
"""Price a manual DK CFB board with the bakeoff-selected PRIOR_CURRENT_BLEND fit.

Works like the MLB card: a quote clears when its edge against the
de-vigged price clears the 2% floor; one team-outcome pick per game
(best of moneyline/spread), totals judged separately. No sportsbook API.

A cleared pick is a BET only if its market is in VALIDATED_MARKETS (beat
52.4% out of sample vs closing lines). The SDV efficiency model failed that
test (#1471: 48.6-49.6% ATS vs close, ~51-52.7% O/U), so today every cleared
pick is a LEAN -- shown for tracking, not a bet.

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
from dataclasses import asdict
from datetime import datetime, timezone
from math import erf, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.market_anchored_spread import (
    VERSION as ANCHORED_SPREAD_VERSION,
    adjusted_home_margin,
    forward_track_eligible,
    load_frozen_fit,
)

# Bakeoff run 37093707442: per-team joint home/away score RMSE.
TEAM_SCORE_RMSE = 12.018
# Margin and total sigma assuming independent home/away residuals.
COMBINED_SIGMA = TEAM_SCORE_RMSE * sqrt(2.0)
EDGE_FLOOR = 0.02  # same floor as the MLB card (#1230)
# An edge this large vs a liquid CFB market is far more likely model error than value.
EDGE_CAP = 0.12
# Markets where this model beat 52.4% out of sample vs closing lines. None yet (#1471, #1476):
# the SDV efficiency model and preseason 247 talent (2016-2025 LOSO, 52.3% vs close) both failed.
VALIDATED_MARKETS: frozenset = frozenset()


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


def price_game(game_id, home: float, away: float, quotes: list, validated=None, spread_context=None) -> list:
    validated = VALIDATED_MARKETS if validated is None else frozenset(validated)
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
        model_home, model_away = home, away
        if market == "SPREAD" and isinstance(spread_context, dict):
            model_home = float(spread_context["home_mean"])
            model_away = float(spread_context["away_mean"])
        p = model_prob(market, side, line, model_home, model_away)
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
            "bet_status": "BET" if EDGE_FLOOR <= edge <= EDGE_CAP else "PASS",
            "reason": ("EDGE_CLEARS_FLOOR" if EDGE_FLOOR <= edge <= EDGE_CAP
                       else "EDGE_TOO_LARGE_SUSPECT" if edge > EDGE_CAP else "BELOW_FLOOR"),
        })
        if market == "SPREAD" and isinstance(spread_context, dict):
            out[-1].update({
                "raw_model_home_margin": round(float(spread_context["raw_model_home_margin"]), 4),
                "market_home_margin": round(float(spread_context["market_home_margin"]), 4),
                "adjusted_home_margin": round(float(spread_context["adjusted_home_margin"]), 4),
                "anchor_adjustment_points": round(float(spread_context["anchor_adjustment_points"]), 4),
                "anchor_forward_track_eligible": bool(spread_context["forward_track_eligible"]),
                "anchor_version": ANCHORED_SPREAD_VERSION,
            })
    # Same-game guard: one team-outcome bet (ML or spread) and one total per game.
    for fam in (("MONEYLINE", "SPREAD"), ("TOTAL",)):
        bets = [r for r in out if r["market"] in fam and r["bet_status"] == "BET"]
        bets.sort(key=lambda r: -r["edge"])
        for r in bets[1:]:
            r["bet_status"], r["reason"] = "PASS", "SAME_GAME_GUARD"
    # Never call an unvalidated model edge a bet.
    for r in out:
        if r["bet_status"] == "BET" and r["market"] not in validated:
            r["bet_status"], r["reason"] = "LEAN", "MODEL_EDGE_NOT_VALIDATED_VS_CLOSE"
        if r["market"] == "SPREAD" and isinstance(spread_context, dict):
            if not bool(spread_context["forward_track_eligible"]):
                if r["bet_status"] == "LEAN":
                    r["bet_status"], r["reason"] = "PASS", "ANCHOR_ADJUSTMENT_BELOW_FORWARD_THRESHOLD"
            elif r["bet_status"] == "LEAN":
                r["reason"] = "MARKET_ANCHORED_SPREAD_FORWARD_TRACK"
    return out


ALIASES = {
    "mississippi": "ole miss", "umass": "massachusetts", "miami oh": "miami (oh)",
    "uconn": "connecticut", "north dakota st": "north dakota state",
    "nc state": "nc state", "usf": "south florida", "fiu": "florida international",
}


def _raw(name: str) -> str:
    import re
    t = re.sub(r"[^a-z0-9() ]", " ", str(name).lower())
    return " ".join(t.split())


def _n(name: str) -> str:
    t = _raw(name)
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
        ra, rh = _raw(row.get("away", "")), _raw(row.get("home", ""))
        def m(want, have, raw_want=None):
            strip = lambda x: x.replace("(", "").replace(")", "")
            cands = {strip(_n(have)), strip(_raw(have))}
            wants = {strip(want)} | ({strip(raw_want)} if raw_want else set())
            return bool(cands & wants)
        _m = m
        m = lambda want, have: _m(want, have, ra if want == a else rh if want == h else None)
        hit = [g for g in games if m(a, g.away_team) and m(h, g.home_team)]
        if not hit:  # neutral-site listings can flip home/away
            hit = [g for g in games if m(a, g.home_team) and m(h, g.away_team)]
    if len(hit) != 1:
        raise SystemExit(f"CFB_SDV_GAME_UNRESOLVED:{row.get('game_id') or (row.get('away'), row.get('home'))}:{len(hit)}")
    return hit[0]


# Live CFBD team metrics are defined differently from the SportsDataverse
# training metrics (e.g. CFBD 'explosiveness' ~1.2 vs SDV explosive-play share
# ~0.075; CFBD off-minus-def start ~0 vs SDV -avg drive field position ~-69;
# yardage success rate vs EPA success rate). Map each live metric onto the
# training scale by matching its cross-team mean/SD to the training feature's
# mean/SD (moment matching). Rank order within the live population is kept.
TEAM_KEYS = ("off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
             "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
             "passing_down_success_rate", "explosive_rate", "net_field_position")


def training_moments(fit_path) -> dict:
    fit = json.loads(Path(fit_path).read_text(encoding="utf-8"))
    names = list(fit["feature_names"])
    out = {}
    for k in TEAM_KEYS:
        ih, ia = names.index("home_" + k), names.index("away_" + k)
        out[k] = ((fit["means"][ih] + fit["means"][ia]) / 2.0, (fit["scales"][ih] + fit["scales"][ia]) / 2.0)
    return out


def moment_match(snaps, moments) -> list:
    report = []
    for side in ("prior", "current"):
        for k in TEAM_KEYS:
            vals = []
            for t in snaps.values():
                m = t.get(side)
                if isinstance(m, dict):
                    try:
                        vals.append(float(m[k]))
                    except (KeyError, TypeError, ValueError):
                        pass
            if len(vals) < 20:
                continue
            mu = sum(vals) / len(vals)
            sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5
            tmu, tsd = moments[k]
            for t in snaps.values():
                m = t.get(side)
                if isinstance(m, dict) and k in m:
                    z = (float(m[k]) - mu) / sd if sd > 1e-12 else 0.0
                    m[k] = tmu + z * tsd
            report.append((side, k, round(mu, 4), round(sd, 4), round(tmu, 4), round(tsd, 4)))
    return report


# Sanity band: a projection outside this means the inputs are broken -> PASS.
MAX_TEAM_POINTS = 75.0
MAX_TOTAL_GAP = 25.0


def projection_sane(home: float, away: float, quotes: list) -> bool:
    if not (0.0 <= home <= MAX_TEAM_POINTS and 0.0 <= away <= MAX_TEAM_POINTS):
        return False
    for q in quotes:
        if str(q.get("market", "")).upper() == "TOTAL" and q.get("line") is not None:
            if abs((home + away) - float(q["line"])) > MAX_TOTAL_GAP:
                return False
    return True


def _live_cache_name(season: int, week: int) -> str:
    return f"live_{int(season)}_w{int(week)}"


def _load_live_week_cache(season: int, week: int, now: datetime, *, load_cache=None):
    """Load a trusted same-week market-blind bundle captured no later than now."""
    if load_cache is None:
        from sportsedge.sports.cfb.cfbd_issue_cache import load_cache as _load_cache
        load_cache = _load_cache
    from sportsedge.sports.cfb.source import CFBGame

    name = _live_cache_name(season, week)
    item = load_cache().get(name)
    if not isinstance(item, dict):
        return None
    if item.get("schema") != "CFB_LIVE_WEEK_CACHE_V1":
        return None
    try:
        if int(item.get("season")) != int(season) or int(item.get("week")) != int(week):
            return None
        captured = datetime.fromisoformat(str(item["captured_at"]).replace("Z", "+00:00"))
        if captured.tzinfo is None or captured.utcoffset() is None:
            return None
        captured = captured.astimezone(timezone.utc)
        if captured > now.astimezone(timezone.utc):
            return None
        games_payload = item.get("games")
        snapshots = item.get("snapshots")
        if not isinstance(games_payload, list) or not games_payload or not isinstance(snapshots, dict) or not snapshots:
            return None
        games = [CFBGame(**dict(row)) for row in games_payload if isinstance(row, dict)]
        if not games:
            return None
    except Exception:
        return None
    print(f"CFB_SDV_LIVE_CACHE_HIT {name} captured_at={captured.isoformat()} games={len(games)} teams={len(snapshots)}")
    return games, snapshots


def _save_live_week_cache(season: int, week: int, now: datetime, games, snapshots, *, save_item=None) -> bool:
    """Persist only market-blind games and candidate snapshots; never sportsbook quotes."""
    if save_item is None:
        from sportsedge.sports.cfb.cfbd_issue_cache import save_item as _save_item
        save_item = _save_item
    name = _live_cache_name(season, week)
    payload = {
        "schema": "CFB_LIVE_WEEK_CACHE_V1",
        "season": int(season),
        "week": int(week),
        "captured_at": now.astimezone(timezone.utc).isoformat(),
        "games": [asdict(game) for game in games],
        "snapshots": snapshots,
    }
    ok = bool(save_item(name, payload))
    if ok:
        print(f"CFB_SDV_LIVE_CACHE_SAVED {name}")
    return ok

def market_implied_scores(quotes: list):
    """(home, away) points implied by the quoted spread and total; None if either is missing."""
    hl = tot = None
    for q in quotes:
        m, side = str(q.get("market", "")).upper(), str(q.get("side", "")).upper()
        if m == "SPREAD" and q.get("line") is not None and hl is None:
            hl = float(q["line"]) if side == "HOME" else -float(q["line"])
        if m == "TOTAL" and q.get("line") is not None and tot is None:
            tot = float(q["line"])
    if hl is None or tot is None:
        return None
    return (tot - hl) / 2.0, (tot + hl) / 2.0


def paired_market_home_margin(quotes: list):
    """Return the paired market-implied home margin, or None on an incomplete/drifting pair."""
    values = []
    sides = set()
    for q in quotes:
        if str(q.get("market") or "").upper() != "SPREAD" or q.get("line") is None:
            continue
        side = str(q.get("side") or "").upper()
        if side not in {"HOME", "AWAY"}:
            continue
        line = float(q["line"])
        values.append(-line if side == "HOME" else line)
        sides.add(side)
    if sides != {"HOME", "AWAY"} or len(values) != 2:
        return None
    if abs(values[0] - values[1]) > 1e-9:
        return None
    return 0.5 * (values[0] + values[1])


def anchored_spread_context(home: float, away: float, quotes: list, fit=None):
    market_margin = paired_market_home_margin(quotes)
    if market_margin is None:
        return None
    frozen = load_frozen_fit() if fit is None else dict(fit)
    raw_margin = float(home) - float(away)
    adjusted = adjusted_home_margin(
        raw_model_home_margin=raw_margin,
        market_home_margin=market_margin,
        intercept=float(frozen["intercept"]),
        weight=float(frozen["weight"]),
    )
    total = float(home) + float(away)
    return {
        "raw_model_home_margin": raw_margin,
        "market_home_margin": market_margin,
        "adjusted_home_margin": adjusted,
        "anchor_adjustment_points": adjusted - market_margin,
        "forward_track_eligible": forward_track_eligible(
            adjusted_margin=adjusted,
            market_home_margin=market_margin,
        ),
        "home_mean": 0.5 * (total + adjusted),
        "away_mean": 0.5 * (total - adjusted),
        "fit_n": int(frozen["n"]),
        "version": ANCHORED_SPREAD_VERSION,
    }


def market_only_rows(board: list, reason: str) -> list:
    """Card rows when the model's data source (CFBD) is down: de-vigged market only.

    model_p is set to the no-vig market price, so edge is 0 and nothing is a bet
    or a lean. Every row is TRACK. This keeps the phone card working (prices,
    fair odds, market-implied scores) instead of posting a traceback.
    """
    out = []
    for i, row in enumerate(board):
        row = expand_compact(row)
        quotes = row.get("quotes") or []
        if not quotes:
            continue
        matchup = (f"{row.get('away')} @ {row.get('home')}" if row.get("away") and row.get("home")
                   else str(row.get("game_id") or f"game {i + 1}"))
        scores = market_implied_scores(quotes)
        home, away = scores if scores else (float("nan"), float("nan"))
        priced = price_game(row.get("game_id"), 0.0, 0.0, quotes)
        for r in priced:
            r.update({
                "matchup": matchup,
                "model_p": r["market_p"],
                "edge": 0.0,
                "home_mean": round(home, 2) if home == home else home,
                "away_mean": round(away, 2) if away == away else away,
                "bet_status": "TRACK",
                "reason": "MODEL_UNAVAILABLE:" + reason,
            })
            out.append(r)
    return out


def build_rows(board: list, season: int, week: int, asof, fit_path=None):
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

    cached = _load_live_week_cache(season, week, now)
    cache_hit = cached is not None
    if cache_hit:
        raw_games, snaps = cached
    else:
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
            cache_hit = False

    if cache_hit:
        # Cached games are already weather-attached from the original PIT run.
        # Reuse those exact market-blind inputs instead of replacing real weather
        # with a later neutral fallback.
        games = raw_games
    else:
        try:
            weather = fetch_cfbd_weather(season=season, week=week, cfbd_api_key=key)
        except Exception as exc:  # CFBD weather is a paid tier; free keys get 401
            print("WEATHER_NEUTRAL_FALLBACK", type(exc).__name__, str(exc)[:120])
            weather = {}
        # Missing weather -> training-mean wind/temp, outdoor: zero standardized weather effect.
        neutral = {"game_indoor": False, "wind_speed": 6.89, "temperature": 64.6, "fallback": "TRAINING_MEAN"}
        games = attach_weather(raw_games, {g.game_id: weather.get(g.game_id) or neutral for g in raw_games})
        snaps = fetch_cfbd_candidate_metric_snapshots(season=season, week=week, cfbd_api_key=key, now=now)
        _save_live_week_cache(season, week, now, games, snaps)
    for line in moment_match(snaps, training_moments(fit_path)):
        print("MOMENT_MATCH side=%s %s live_mean=%s live_sd=%s -> train_mean=%s train_sd=%s" % line)
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



def attach_cfb_both_sides(payload: dict) -> dict:
    """List both sides of quoted CFB markets plus the prop/side/total catalog.

    Does not change bet_status. Missing quotes stay BLOCKED. Not official.
    """
    from sportsedge.football_full_board import board_from_machine_results, catalog_complete

    rows = []
    for raw in payload.get("results") or []:
        if not isinstance(raw, dict) or not raw.get("market"):
            continue
        rows.append({
            "game_id": raw.get("game_id") or raw.get("matchup"),
            "market": str(raw.get("market") or "").lower(),
            "side": raw.get("side"),
            "selection": raw.get("side"),
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds"),
            "model_p": raw.get("model_p"),
            "entity_id": raw.get("entity_id") or raw.get("player"),
            "reason": raw.get("reason") or "QUOTED_PHONE_SIDE",
        })
    board = board_from_machine_results("CFB", rows)
    payload["full_board"] = board
    payload["both_sides"] = board["summary"]["both_sides"]
    payload["catalog_complete"] = catalog_complete(board["summary"])
    payload["side_rows"] = board["summary"]["side_rows"]
    payload["total_rows"] = board["summary"]["total_rows"]
    payload["prop_rows"] = board["summary"]["prop_rows"]
    return payload


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
    if isinstance(board, dict) and board.get("backtest") == "talent_mirror":
        # No CFBD calls: talent vs closing spread from pinned public mirrors (#1476).
        import importlib.util
        spec = importlib.util.spec_from_file_location("cfb_tm", ROOT / "scripts" / "backtest_cfb_talent_mirror.py")
        tm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tm)
        return tm.main([], board=board)
    if isinstance(board, dict) and board.get("backtest") == "residual":
        import importlib.util
        spec = importlib.util.spec_from_file_location("cfb_rf", ROOT / "scripts" / "backtest_cfb_residual_features.py")
        rf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rf)
        return rf.main([])
    if isinstance(board, dict) and board.get("backtest"):
        # Phone-issue hook: run the leave-one-season-out backtest vs CFBD closing lines.
        import importlib.util
        spec = importlib.util.spec_from_file_location("cfb_bt", ROOT / "scripts" / "backtest_cfb_sdv_vs_lines.py")
        bt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bt)
        return bt.main([])
    if not isinstance(board, list) or not board:
        raise SystemExit("CFB_SDV_BOARD_ARRAY_REQUIRED")
    model = load_selected_sdv_fit(args.fit)
    results = []
    fallback = None
    try:
        game_rows = build_rows(board, args.season, args.week, args.asof, args.fit)
    except (Exception, SystemExit) as exc:  # CFBD quota/outage or unresolvable names
        msg = str(exc)
        fallback = ("CFBD_RATE_LIMITED" if "429" in msg else
                    "CFBD_KEY_MISSING" if "API_KEY_REQUIRED" in msg else
                    "NO_GAMES_RESOLVED" if "NO_GAMES_RESOLVED" in msg else
                    "CFBD_SOURCE_FAILED")
        print(f"CFB_SDV_MARKET_ONLY model data unavailable ({fallback}: {msg[:160]}); "
              "card shows no-vig market prices and market-implied scores only, 0 bets, 0 leans")
        game_rows = []
        results = market_only_rows(board, fallback)
        if not results:
            raise
    for row in game_rows:
        try:
            blind = {k: v for k, v in row.items() if k != "quotes"}  # model is market-blind
            home, away = score_selected_game(model, blind)
        except Exception as exc:
            print("SKIPPED CFB_SDV_SCORE_FAILED", row.get("away_team"), "@", row.get("home_team"), exc)
            continue
        if not projection_sane(home, away, row.get("quotes") or []):
            print(f"SKIPPED CFB_SDV_PROJECTION_INSANE {row.get('away_team')} @ {row.get('home_team')} {away:.1f}-{home:.1f}")
            continue
        quotes = row.get("quotes") or []
        spread_context = anchored_spread_context(home, away, quotes)
        priced = price_game(
            row["game_id"], home, away, quotes,
            spread_context=spread_context,
        )
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
        "validated_markets": sorted(VALIDATED_MARKETS),
        "market_anchored_spread": {
            "version": ANCHORED_SPREAD_VERSION,
            "fit_status": "FROZEN_FORWARD_TRACKING_READY",
            "tracking_issue": 1602,
            "minimum_absolute_adjustment_points": 0.5,
            "historical_evidence_role": "DEVELOPMENT_ONLY_ALREADY_TOUCHED",
            "forward_validated": False,
        },
        "model_status": "MARKET_ONLY:" + fallback if fallback else "MODEL",
        "bets": sum(r.get("bet_status") == "BET" for r in results),
        "leans": sum(r.get("bet_status") == "LEAN" for r in results),
        "results": sorted(results, key=lambda r: -(r.get("edge") or -9)),
    }
    payload = attach_cfb_both_sides(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Visible in the phone comment (lines containing CFB_SDV_ are echoed).
    leans = [r for r in payload["results"] if r.get("bet_status") == "LEAN"]
    if not VALIDATED_MARKETS and not fallback:
        print("CFB_SDV_NO_VALIDATED_EDGE model failed out-of-sample test vs closing lines (#1471); "
              f"{len(leans)} leans below are tracking only, not bets")
    for r in leans:
        ln = "" if r["line"] in (None, "") else (f" {float(r['line']):+g}" if r["market"] == "SPREAD" else f" {float(r['line']):g}")
        print(f"CFB_SDV_LEAN {r['matchup']}: {r['market'].title()} {r['side'].title()}{ln} {r['american_odds']:+.0f} "
              f"model {r['model_p']*100:.1f}% vs mkt {r['market_p']*100:.1f}% ({r['edge']*100:+.1f}%)")
    for r in payload["results"]:
        if "edge" in r:
            print(f"{r['bet_status']:4s} {r['matchup']:45s} {r['market']:9s} {r['side']:5s} {str(r['line'] or ''):6s} "
                  f"{r['american_odds']:+6.0f}  model {r['model_p']*1:.3f}  mkt {r['market_p']:.3f}  edge {r['edge']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
