"""Phone-only NFL player-prop intake: user odds, independently fetched model data.

The user's JSON supplies quotes and player display names, never p or history.
This module resolves identity and prior game logs solely via free ESPN endpoints.
Research only. Stale quotes produce WATCH status. Next Gen tracking is not yet
consumed. Lineup/participation is not confirmed from gamelog.

Participation wiring (Oct 2026): when the caller supplies a
``participation`` evidence bundle (nflverse depth/injury rows, official
inactive designations, per-game contexts, and explicit ESPN<->nflverse
player bindings), each priced row is checked against the participation
bridge's verdict for that exact (game, team, player).  A confirmed-tier
verdict (``CONFIRMED_STARTER`` / ``CONFIRMED_ACTIVE`` from game-day
actives) replaces the ``STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG`` stamp
with the verdict state and the candidate keeps its research status; every
other outcome keeps the stamp and records the bridge's named refusal.
The bundle changes evidence quality only -- labels, eligibility and
authority flags are identical either way.  With no bundle supplied the
behavior is byte-for-byte the historical one: the gamelog alone can
never verify a role, so the stamp always applies.
"""
from __future__ import annotations
from datetime import datetime, timezone

from .nfl_participation_bridge import (
    NFLParticipationError, assess_qb_participation,
    assess_skill_participation, require_confirmed_qb_role,
    require_confirmed_skill_role)
from .nfl_public_player_history import NFLPlayerPublicSource, MissingNFLHistory
from .nfl_player_empirical import price_nfl_player_market, NFLEmpiricalError
from .research_three_sport_bridge import price_three_sport_research
from .sports.nfl.live_role_source import _team as _nfl_team_code

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


# Markets graded by the QB slot machine; every other supported market is
# graded by the skill-player machine (the player's own chart row).
_PASSING_MARKETS = frozenset({
    "PLAYER_PASSING_YARDS", "PLAYER_PASS_YARDS", "PLAYER_PASS_TDS",
    "PLAYER_PASSING_TDS", "PLAYER_PASS_ATTEMPTS", "PLAYER_COMPLETIONS",
    "PLAYER_INTERCEPTIONS", "PLAYER_PASS_PLUS_RUSH_YARDS",
})
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _norm_person_name(value):
    tokens = [
        t for t in "".join(
            c if c.isalnum() else " "
            for c in str(value or "").casefold()).split()
        if t not in _NAME_SUFFIXES]
    return " ".join(tokens)


def _instant(value):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo is not None else None


def _participation_context(participation, *, away, home, start):
    """The bundle's game context for this phone fixture, or None."""
    for ctx in participation.get("games") or ():
        if str(ctx.get("away") or "") != away:
            continue
        if str(ctx.get("home") or "") != home:
            continue
        ctx_kick, row_kick = _instant(ctx.get("kickoff")), _instant(start)
        if ctx_kick is not None and row_kick is not None \
                and ctx_kick != row_kick:
            continue
        return ctx
    return None


def _participation_binding(participation, *, player_name, ctx):
    """The caller's explicit ESPN<->nflverse binding for this player.

    The phone path resolves ESPN athlete ids; the bridge grades nflverse
    GSIS ids.  The two namespaces are never guessed across: intake joins
    them in a binding row (player name + nflverse team code + GSIS id),
    and a row without exactly such a binding keeps the gamelog stamp.
    """
    codes = {_nfl_team_code(ctx.get("away_code")),
             _nfl_team_code(ctx.get("home_code"))} - {""}
    wanted = _norm_person_name(player_name)
    for binding in participation.get("player_bindings") or ():
        if _norm_person_name(binding.get("player_name")) != wanted:
            continue
        if codes and _nfl_team_code(binding.get("team")) not in codes:
            continue
        return binding
    return None


def _participation_verdict(participation, *, market, verified, away, home,
                           start, now_utc):
    """Bridge verdict for one phone row: (verdict | None, refusal | None).

    A non-None refusal is the named reason the gamelog stamp stays: the
    bridge gate's own refusal string when a verdict was computed, or a
    PARTICIPATION_* name when the bundle cannot even address this row.
    """
    ctx = _participation_context(
        participation, away=away, home=home, start=start)
    if ctx is None:
        return None, "PARTICIPATION_GAME_CONTEXT_MISSING"
    binding = _participation_binding(
        participation, player_name=verified["player_name"], ctx=ctx)
    if binding is None:
        return None, "PARTICIPATION_PLAYER_BINDING_MISSING"
    try:
        season, week = int(ctx["season"]), int(ctx["week"])
    except (KeyError, TypeError, ValueError):
        return None, "PARTICIPATION_GAME_CONTEXT_INCOMPLETE"
    team_code = _nfl_team_code(binding.get("team"))
    pid = str(binding.get("player_id") or "").strip()
    if not team_code or not pid:
        return None, "PARTICIPATION_PLAYER_BINDING_INCOMPLETE"
    common = dict(
        depth_rows=participation.get("depth_rows") or (),
        injury_rows=participation.get("injury_rows") or (),
        inactive_rows=participation.get("inactive_rows") or (),
        game_id=ctx.get("game_id"), target_season=season,
        target_week=week, kickoff=ctx.get("kickoff") or start,
        as_of=now_utc)
    verdict = None
    try:
        if market in _PASSING_MARKETS:
            verdict = assess_qb_participation(
                team=team_code, expected_player_id=pid, **common)
            require_confirmed_qb_role(
                verdict, depth_rows=common["depth_rows"], as_of=now_utc)
        else:
            verdict = assess_skill_participation(
                team=team_code, player_id=pid,
                position=binding.get("position"), **common)
            require_confirmed_skill_role(verdict)
    except NFLParticipationError as exc:
        return verdict, str(exc)
    if _norm_person_name(verdict.get("candidate_name")) != \
            _norm_person_name(verified["player_name"]):
        return verdict, f"NFL_PARTICIPATION_IDENTITY_BINDING_MISMATCH:{pid}"
    return verdict, None


def phone_nfl_player_rows(rows, *, now=None, getter=None, participation=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    now_utc = now.astimezone(timezone.utc).isoformat()
    src = NFLPlayerPublicSource(getter=getter)
    outputs = []
    cache = {}
    verdict_cache = {}
    part_by_key = {}

    def verdict_for(key, market, verified, away, home, start):
        """Bridge verdict per (player, market family), computed once."""
        family = "QB" if market in _PASSING_MARKETS else "SKILL"
        ck = (key, family)
        if ck not in verdict_cache:
            verdict_cache[ck] = _participation_verdict(
                participation, market=market, verified=verified,
                away=away, home=home, start=start, now_utc=now_utc)
            verdict, refusal = verdict_cache[ck]
            entry = part_by_key.setdefault(
                key, {"verdict": None, "refusal": None})
            if verdict is not None and refusal is None:
                entry["verdict"], entry["refusal"] = verdict, None
            elif entry["verdict"] is None:
                entry["verdict"], entry["refusal"] = verdict, refusal
        return verdict_cache[ck]
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
                "quote_captured_at": another.get("quote_captured_at"),
            })
        judged = price_three_sport_research([p], quotes, as_of=now_utc)["rows"][0]
        judged["line"] = line
        judged["player_name"] = verified["player_name"]
        judged["prior_game_count"] = verified["prior_game_count"]
        judged["source"] = "FREE_ESPN_NFL_GAMELOG"
        judged["source_game_id"] = verified["game_id"]
        judged["stats_schema"] = "ESPN_EXPLICIT_NAMES_ONLY"
        judged["participation_status"] = "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
        role_confirmed = False
        if participation is not None:
            verdict, refusal = verdict_for(
                key, market, verified, away, home, start)
            if verdict is not None:
                judged["participation_verdict"] = verdict
            if verdict is not None and refusal is None:
                # Confirmed by gamelog-independent evidence as of the
                # pricing cutoff: the stamp lifts and the row keeps its
                # research-candidate status.  Labels/authority unchanged.
                judged["participation_status"] = verdict["state"]
                role_confirmed = True
            elif refusal is not None:
                judged["participation_refusal"] = refusal
        # Prior-game stats do not verify expected snaps/targets or active role.
        # A small-sample historical estimate may appear on the watchlist,
        # but cannot be treated as a current-price research candidate --
        # unless the participation bridge confirmed the role above.
        if not role_confirmed and \
                judged.get("status") == "RESEARCH_CANDIDATE_NOT_VALIDATED":
            judged["status"] = "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
        outputs.append(judged)
    receipts = []
    for key, d in cache.items():
        if not isinstance(d, dict):
            continue
        entry = part_by_key.get(key) or {}
        verdict = entry.get("verdict")
        receipt = {
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
            "participation": verdict["state"] if verdict else "NOT_VERIFIED",
        }
        if verdict is not None:
            receipt["participation_subclass"] = verdict.get("subclass")
            receipt["participation_team"] = verdict.get("team")
            receipt["participation_player_id"] = verdict.get("candidate_id")
            receipt["participation_as_of"] = verdict.get("as_of")
        if entry.get("refusal"):
            receipt["participation_refusal"] = entry["refusal"]
        receipts.append(receipt)
    return outputs, receipts
