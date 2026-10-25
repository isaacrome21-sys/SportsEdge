"""Phone-only MLB batter-prop intake: user odds, independently fetched model data.

The user's JSON supplies quotes and player display names, never p or history.
This module resolves identity and prior game logs solely via free MLB StatsAPI.
Research only. Stale quotes produce WATCH status. Lineup is not confirmed.
"""
from __future__ import annotations
from datetime import datetime, timezone

from .mlb_public_batter_history import MLBBatterPublicSource, MissingMLBBatterHistory
from .research_model_adapters import mlb_batter_to_bridge_rows
from .research_three_sport_bridge import price_three_sport_research
from .quoted_count_threshold import same_quoted_count_threshold

BATTER_MARKETS = frozenset({
    "BATTER_HITS", "BATTER_TOTAL_BASES", "BATTER_RBIS", "BATTER_RUNS",
    "BATTER_HRS", "BATTER_HOME_RUNS", "BATTER_STOLEN_BASES",
    "BATTER_BB", "BATTER_WALKS", "BATTER_K", "BATTER_STRIKEOUTS",
    "BATTER_SINGLES", "SINGLES", "BATTER_DOUBLES", "DOUBLES",
    "BATTER_TRIPLES", "TRIPLES",
    "BATTER_EXTRA_BASE_HITS", "EXTRA_BASE_HITS",
    "BATTER_RUNS_RBIS", "RUNS_RBIS",
    "HITS_RUNS_RBIS", "H_R_RBI",
})


def blocked(row, reason):
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "sport": "MLB", "market": row.get("market"),
            "selection": row.get("side"), "player_name": row.get("player_name"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False}


def phone_batter_rows(rows, *, now=None, getter=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now_utc = now.astimezone(timezone.utc).isoformat()
    src = MLBBatterPublicSource(getter=getter)
    outputs = []
    cache = {}
    for row in rows:
        market = str(row.get("market") or "").upper()
        if market not in BATTER_MARKETS:
            outputs.append(blocked(row, "MARKET_NOT_SUPPORTED_BY_BATTER_EMPIRICAL"))
            continue
        name = str(row.get("player_name") or row.get("label") or "").strip()
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        start = row.get("kickoff") or row.get("commence_time")
        key = (away, home, str(start), name)
        if key not in cache:
            try:
                if not name or not away or not home or not start:
                    raise MissingMLBBatterHistory("GAME_BATTER_IDENTITY_OR_KICKOFF_MISSING")
                cache[key] = src.prior_games(away=away, home=home,
                                             player_name=name,
                                             owner_kickoff=start, as_of=now_utc)
            except (MissingMLBBatterHistory, TypeError, ValueError, KeyError) as exc:
                cache[key] = str(exc)
        verified = cache[key]
        if not isinstance(verified, dict):
            outputs.append(blocked(row, verified))
            continue
        side = str(row.get("side") or row.get("selection") or "").upper()
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError):
            outputs.append(blocked(row, "BATTER_PROP_LINE_UNVERIFIED"))
            continue
        p = mlb_batter_to_bridge_rows(
            game_id=verified["game_id"], player_id=verified["batter_id"],
            market=market, side=side, line=line,
            features=verified["features"],
            prior_game_times_utc=verified["prior_game_times_utc"],
            prior_game_ids=verified.get("prior_game_ids"),
            source_as_of_utc=verified["source_as_of_utc"], as_of_utc=now_utc,
            kickoff_utc=verified["kickoff_utc"],
            home_team=home, away_team=away,
        )[0]
        if p.get("status") != "PRICED_RESEARCH":
            outputs.append(blocked(row, p.get("reason") or "BATTER_MODEL_UNAVAILABLE"))
            continue
        quotes = []
        for another in rows:
            if (str(another.get("away")) != away or
                str(another.get("home")) != home or
                str(another.get("player_name") or another.get("label") or "").strip() != name or
                str(another.get("market") or "").upper() != market or
                not same_quoted_count_threshold(another.get("line"), row.get("line"))):
                continue
            quotes.append({
                "sport": "MLB", "game_id": verified["game_id"],
                "market": market, "line": line,
                "selection": str(another.get("side") or another.get("selection") or "").upper(),
                "player_id": verified["batter_id"],
                "odds": another.get("odds", another.get("price")),
                "book": another.get("book") or "draftkings",
                "quote_captured_at": (another.get("quote_captured_at")
                                      or another.get("captured_at")),
            })
        judged = price_three_sport_research([p], quotes, as_of=now_utc)["rows"][0]
        judged["line"] = line
        judged["player_name"] = verified["batter_name"]
        judged["lineup_status"] = verified["lineup_status"]
        judged["prior_game_count"] = verified["prior_game_count"]
        judged["prior_plate_appearances"] = verified["prior_plate_appearances"]
        # Historical game rates do not guarantee today's playing time. Never
        # surface a current-price research candidate without an independently
        # verified official starting batting order.
        if not verified["lineup_verified"] and judged.get("status") == "RESEARCH_CANDIDATE_NOT_VALIDATED":
            judged["status"] = "WATCH_LINEUP_NOT_CONFIRMED"
        judged["source"] = "FREE_MLB_STATSAPI_BATTER_GAMELOG"
        judged["source_game_id"] = verified["game_id"]
        outputs.append(judged)
    return outputs, [{
        "source": d["source_endpoint"],
        "status": "PUBLIC_MLB_PRIOR_BATTER_GAMES_VERIFIED",
        "batter_id": d["batter_id"],
        "prior_games": d["prior_game_count"],
        "prior_plate_appearances": d["prior_plate_appearances"],
        "lineup": d["lineup_status"],
    } for d in cache.values() if isinstance(d, dict)]
