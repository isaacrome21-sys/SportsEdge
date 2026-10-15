"""Phone-only MLB pitcher-prop intake: user odds, *independently fetched* model data.

The user's JSON supplies quotes and player display names, never p, PIT history
or verification authority. This module resolves player/team/game identity and
history solely via free MLB StatsAPI. Only pregame. Returning WATCH for stale
quotes is intentional; a stale screenshot is NOT an executable edge.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Mapping

from .mlb_public_pitcher_history import MLBPitcherPublicSource, MissingMLBHistory
from .research_model_adapters import mlb_pitcher_to_bridge_rows
from .research_three_sport_bridge import price_three_sport_research
from .quoted_count_threshold import same_quoted_count_threshold

PITCHER_MARKETS = frozenset({
    "PITCHER_K", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED",
    "PITCHER_BB", "PITCHER_ER", "PITCHER_PITCHES", "PITCHER_HITS_WALKS_ER",
})


# DK board names for pitcher strikeouts. The pitcher lane canonicalizes
# them to PITCHER_K (for the row AND its companion quotes) so the real
# pitcher engine prices them. Pairing, freshness and the pitcher-K forward
# hold are unchanged.
PITCHER_MARKET_ALIASES = {
    "PITCHER_STRIKEOUTS": "PITCHER_K", "PITCHER_KS": "PITCHER_K",
    "STRIKEOUTS": "PITCHER_K",
}


def _canonical_market(value):
    market = str(value or "").upper()
    return PITCHER_MARKET_ALIASES.get(market, market)


PITCHER_K_ANNEX_WITHHELD = "PITCHER_K_FORWARD_HOLD_RESEARCH_ESTIMATE_WITHHELD"


def withhold_pitcher_k_annex(judged, market):
    """Pitcher K stays under its forward hold (6/150): no research annex.

    The row keeps its named blocker; the estimate is withheld by name so the
    card never shows a pitcher-K probability while the hold is open.
    """
    if market == "PITCHER_K" and isinstance(judged, dict) and "research_estimate" in judged:
        judged.pop("research_estimate", None)
        judged["research_estimate_withheld"] = PITCHER_K_ANNEX_WITHHELD
    return judged


def blocked(row, reason):
    return {"status": "NO_MODEL_OR_MARKET", "reason": str(reason)[:180],
            "sport": "MLB", "market": row.get("market"),
            "selection": row.get("side"), "player_name": row.get("player_name"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False}


def phone_pitcher_rows(rows, *, now=None, getter=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now_utc = now.astimezone(timezone.utc).isoformat()
    src = MLBPitcherPublicSource(getter=getter)
    outputs = []
    cache = {}
    for row in rows:
        market = _canonical_market(row.get("market"))
        if market not in PITCHER_MARKETS:
            outputs.append(blocked(row,"MARKET_NOT_SUPPORTED_BY_REAL_PITCHER_ENGINE"))
            continue
        name = str(row.get("player_name") or row.get("label") or "").strip()
        away = str(row.get("away") or "").strip()
        home = str(row.get("home") or "").strip()
        start = row.get("kickoff") or row.get("commence_time")
        key = (away, home, str(start), name)
        if key not in cache:
            try:
                if not name or not away or not home or not start:
                    raise MissingMLBHistory("GAME_PITCHER_IDENTITY_OR_KICKOFF_MISSING")
                cache[key] = src.prior_starts(away=away, home=home,
                                              player_name=name,
                                              owner_kickoff=start, as_of=now_utc)
            except (MissingMLBHistory, TypeError, ValueError, KeyError) as exc:
                cache[key] = str(exc)
        verified = cache[key]
        if not isinstance(verified, dict):
            outputs.append(blocked(row, verified))
            continue
        side = str(row.get("side") or row.get("selection") or "").upper()
        try:
            line = float(row["line"])
        except (KeyError, TypeError, ValueError):
            outputs.append(blocked(row,"PITCHER_PROP_LINE_UNVERIFIED"))
            continue
        p = mlb_pitcher_to_bridge_rows(
            game_id=verified["game_id"], player_id=verified["pitcher_id"],
            market=market, side=side, line=line,
            features=verified["features"],
            prior_start_times_utc=verified["prior_start_times_utc"],
            source_as_of_utc=verified["source_as_of_utc"], as_of_utc=now_utc,
            kickoff_utc=verified["kickoff_utc"],
            starting_pitcher_verified=verified["probable_pitcher_verified"],
            home_team=home, away_team=away,
        )[0]
        if p.get("status") != "PRICED_RESEARCH":
            outputs.append(blocked(row,p.get("reason") or "PITCHER_MODEL_UNAVAILABLE"))
            continue
        # Derive the companion quote ONLY from the same screenshot rows.
        # Match exact player identity, market, threshold and matchup;
        # never use model probability supplied through issue data.
        quotes = []
        for another in rows:
            if (str(another.get("away")) != away or
                str(another.get("home")) != home or
                str(another.get("player_name") or another.get("label") or "").strip() != name or
                _canonical_market(another.get("market")) != market or
                not same_quoted_count_threshold(another.get("line"), row.get("line"))):
                continue
            quotes.append({
                "sport":"MLB", "game_id": verified["game_id"],
                "market": market, "line": line,
                "selection": str(another.get("side") or another.get("selection") or "").upper(),
                "player_id": verified["pitcher_id"],
                "odds": another.get("odds",another.get("price")),
                "book": another.get("book") or "draftkings",
                "quote_captured_at": another.get("quote_captured_at"),
            })
        judged = withhold_pitcher_k_annex(
            price_three_sport_research([p],quotes,as_of=now_utc)["rows"][0], market)
        # The generic bridge returns pricing fields but does not echo the
        # market threshold. Preserve the independently matched quoted line.
        judged["line"] = line
        judged["player_name"] = verified["pitcher_name"]
        judged["pitcher_status"] = "PROBABLE_STARTER_ONLY_NOT_CONFIRMED"
        judged["prior_start_count"] = verified["prior_start_count"]
        judged["source"] = "FREE_MLB_STATSAPI_GAMELOG"
        judged["source_game_id"] = verified["game_id"]
        outputs.append(judged)
    return outputs, [{
        "source": d["source_endpoint"],
        "status": "PUBLIC_MLB_PRIOR_STARTS_VERIFIED",
        "pitcher_id": d["pitcher_id"],
        "prior_starts": d["prior_start_count"],
        "starter": "PROBABLE_NOT_CONFIRMED",
    } for d in cache.values() if isinstance(d, dict)]
