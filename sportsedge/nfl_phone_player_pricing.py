"""Phone-only NFL player-prop intake: user odds, independently fetched model data.

The user's JSON supplies quotes and player display names, never p or history.
This module resolves identity and prior game logs solely via free ESPN endpoints.
Research only. Stale quotes produce WATCH status. Next Gen tracking is not yet
consumed. Lineup/participation is not confirmed from gamelog.
"""
from __future__ import annotations
from datetime import datetime, timezone

from .nfl_public_player_history import NFLPlayerPublicSource, MissingNFLHistory
from .nfl_player_empirical import price_nfl_player_market, NFLEmpiricalError
from .research_three_sport_bridge import price_three_sport_research

NFL_PLAYER_MARKETS = frozenset({
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_YARDS", "PLAYER_PASS_TDS",
    "PLAYER_PASSING_TDS", "PLAYER_PASS_ATTEMPTS", "PLAYER_COMPLETIONS",
    "PLAYER_INTERCEPTIONS", "PLAYER_RUSHING_YARDS", "PLAYER_RUSH_YARDS",
    "PLAYER_RUSH_ATTEMPTS", "PLAYER_RECEIVING_YARDS", "PLAYER_REC_YARDS",
    "PLAYER_RECEPTIONS", "PLAYER_RUSH_PLUS_REC_YARDS",
    "PLAYER_PASS_PLUS_RUSH_YARDS",
})


def blocked(row, reason):
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "sport": "NFL", "market": row.get("market"),
            "selection": row.get("side"), "player_name": row.get("player_name"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False}


def phone_nfl_player_rows(rows, *, now=None, getter=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now_utc = now.astimezone(timezone.utc).isoformat()
    src = NFLPlayerPublicSource(getter=getter)
    outputs = []
    cache = {}
    for row in rows:
        market = str(row.get("market") or "").upper()
        if market not in NFL_PLAYER_MARKETS:
            outputs.append(blocked(row, "MARKET_NOT_SUPPORTED_BY_NFL_EMPIRICAL"))
            continue
        name = str(row.get("player_name") or row.get("label") or "").strip()
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        start = row.get("kickoff") or row.get("commence_time")
        key = (away, home, str(start), name)
        if key not in cache:
            try:
                if not name or not away or not home or not start:
                    raise MissingNFLHistory("GAME_PLAYER_IDENTITY_OR_KICKOFF_MISSING")
                cache[key] = src.prior_games(away=away, home=home,
                                             player_name=name,
                                             owner_kickoff=start, as_of=now_utc)
            except (MissingNFLHistory, TypeError, ValueError, KeyError) as exc:
                cache[key] = str(exc)
        verified = cache[key]
        if not isinstance(verified, dict):
            outputs.append(blocked(row, verified))
            continue
        side = str(row.get("side") or row.get("selection") or "").upper()
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError):
            outputs.append(blocked(row, "NFL_PROP_LINE_UNVERIFIED"))
            continue
        try:
            outcome = price_nfl_player_market(
                market=market, side=side, line=line,
                game_history=verified["features"]["game_history"])
        except (NFLEmpiricalError, KeyError, TypeError) as exc:
            outputs.append(blocked(row, str(exc)))
            continue
        p = {
            "sport": "NFL", "game_id": verified["game_id"],
            "market": market, "selection": side,
            "estimate_p": outcome["model_p"], "push_p": outcome["push_p"],
            "status": "PRICED_RESEARCH", "market_blind": True,
            "model_source": outcome["engine"],
            "as_of_utc": now_utc, "kickoff_utc": verified["kickoff_utc"],
            "phase": "PREGAME", "validated_vs_close": False,
            "official_authority": False, "model_p_authority": False,
            "staking_authority": False, "research_only": True,
            "player_id": verified["player_id"], "line": line,
            "home_team": home, "away_team": away,
        }
        quotes = []
        for another in rows:
            if (str(another.get("away")) != away or
                str(another.get("home")) != home or
                str(another.get("player_name") or another.get("label") or "").strip() != name or
                str(another.get("market") or "").upper() != market or
                another.get("line") != row.get("line")):
                continue
            quotes.append({
                "sport": "NFL", "game_id": verified["game_id"],
                "market": market, "line": line,
                "selection": str(another.get("side") or another.get("selection") or "").upper(),
                "player_id": verified["player_id"],
                "odds": another.get("odds", another.get("price")),
                "book": another.get("book") or "draftkings",
                "quote_captured_at": (another.get("quote_captured_at")
                                      or another.get("captured_at")),
            })
        judged = price_three_sport_research([p], quotes, as_of=now_utc)["rows"][0]
        judged["line"] = line
        judged["player_name"] = verified["player_name"]
        judged["prior_game_count"] = verified["prior_game_count"]
        judged["source"] = "FREE_ESPN_NFL_GAMELOG"
        judged["source_game_id"] = verified["game_id"]
        judged["stats_schema"] = "ESPN_EXPLICIT_NAMES_ONLY"
        judged["participation_status"] = "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
        # Prior-game stats do not verify expected snaps/targets or active role.
        # A small-sample historical estimate may appear on the watchlist,
        # but cannot be treated as a current-price research candidate.
        if judged.get("status") == "RESEARCH_CANDIDATE_NOT_VALIDATED":
            judged["status"] = "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
        outputs.append(judged)
    return outputs, [{
        "source": d["source_endpoint"],
        "status": "PUBLIC_NFL_PRIOR_GAMES_VERIFIED",
        "player_id": d["player_id"],
        "prior_games": d["prior_game_count"],
        "prior_game_seasons": d.get("prior_game_seasons", []),
        "prior_season_history_years": d.get("prior_season_history_years", []),
        "history_finality_rule": d.get("history_finality_rule"),
        "stat_fields": d["explicit_stat_fields"],
        "schema_rejected_prior_events": d["schema_rejected_prior_events"],
        "schema_rejected_prior_reasons": d.get("schema_rejected_prior_reasons", {}),
        "participation": "NOT_VERIFIED",
    } for d in cache.values() if isinstance(d, dict)]
