"""Canonical phone adapter: NFL anytime-TD (and first-TD assessment).

Wires the complete fail-closed library engine
(``sportsedge.nfl_anytime_td``) into the canonical RUN IT path:

* ANYTIME_TD rows are priced from strictly point-in-time nflverse history
  (cached first; fetched only through the caller's opener seam).  The
  engine itself enforces identity resolution, history depth, and the
  snap-share participation gate -- this adapter never relaxes them.
* The engine's P(any TD) becomes a Lane-A model row judged against the
  paired YES/NO DraftKings quotes by the standard research bridge, which
  enforces the 180-second quote-freshness rule and exact pairing.
* FIRST_TD rows resolve through the engine's own feasibility assessment
  (``assess_first_td``) and stay blocked with its reason
  ``NO_VERIFIED_FIRST_SCORING_ATTRIBUTION`` (taxonomy NO_DATA).

Team identity accepts the nflverse abbreviation or any alias in
``sportsedge.nfl_team_aliases``; anything unresolved fails closed with
``TD_TEAM_IDENTITY_UNVERIFIED`` rather than guessing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from sportsedge.nfl_anytime_td import (
    NflTdError,
    assess_first_td,
    blocked_anytime_td,
    estimate_anytime_td,
    load_td_history,
    resolve_player_id,
)
from sportsedge.nfl_team_aliases import NFL_TEAMS
from sportsedge.research_three_sport_bridge import price_three_sport_research

TD_SOURCE = "FREE_NFLVERSE_ANYTIME_TD"
TD_MARKETS = {"ANYTIME_TD", "ANYTIME_TOUCHDOWN"}
FIRST_TD_MARKETS = {"FIRST_TD", "FIRST_TOUCHDOWN"}

_ALIAS_TO_ABBR: dict[str, str] = {}
for _abbr, _names in NFL_TEAMS.items():
    _ALIAS_TO_ABBR[_abbr.upper()] = _abbr
    for _name in _names:
        _ALIAS_TO_ABBR[str(_name).strip().upper()] = _abbr


def team_abbreviation(value: Any) -> str | None:
    """nflverse abbreviation for an abbreviation or known alias, else None."""
    return _ALIAS_TO_ABBR.get(str(value or "").strip().upper())


def _parse_kickoff(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _history_seasons(kickoff: datetime) -> tuple[tuple[int, ...], tuple[int, ...]]:
    year = kickoff.year
    return (year - 1, year), (year,)


def _load_history(kickoff: datetime, *, cache_dir, opener):
    """Load history, retrying without the prior season when ONLY it failed.

    Returns (history, seasons_used).  A missing prior season (e.g. early
    in a season with no cache yet) must not block the current season;
    any other failure propagates as NflTdError (fail closed).
    """
    primary, fallback = _history_seasons(kickoff)
    effective_opener = opener if opener is not None else urlopen
    try:
        return load_td_history(seasons=primary, cache_dir=cache_dir,
                               opener=effective_opener), primary
    except NflTdError as exc:
        tag = str(exc)
        if str(primary[0]) in tag:
            return load_td_history(seasons=fallback, cache_dir=cache_dir,
                                   opener=effective_opener), fallback
        raise


def _resolve_fixture(history: Mapping[str, Any], *, team: str, opponent: str):
    """(game_id, kickoff) of the unique games-table fixture for the pair.

    The games table kickoff is authoritative: it is the strict PIT key the
    engine prices against, never the intake row's own claim.
    """
    games = history.get("games")
    if games is None:
        return None, "TD_GAMES_TABLE_UNAVAILABLE"
    matches = []
    for _, game in games.iterrows():
        pair = {str(game.get("home_team") or "").upper(),
                str(game.get("away_team") or "").upper()}
        if pair == {team, opponent} and game.get("kickoff") is not None:
            matches.append((str(game.get("game_id") or ""), game["kickoff"]))
    if not matches:
        return None, "TD_FIXTURE_NOT_IN_VERIFIED_GAMES_TABLE"
    if len(matches) > 1:
        return None, "TD_FIXTURE_AMBIGUOUS_IN_GAMES_TABLE"
    return matches[0], None


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _odds(value: Any) -> int | None:
    parsed = _num(value)
    return int(parsed) if parsed is not None else None


def _evaluation_time(now, row):
    """Bridge as_of: the evaluation instant, never the game kickoff.

    The bridge enforces ``kickoff > as_of`` strictly (pregame) and
    measures the 180-second quote-freshness rule against ``as_of``.
    """
    if isinstance(now, datetime):
        evaluated = now
    else:
        evaluated = None
    if evaluated is None:
        for other_key in ("quote_captured_at",):
            parsed = _parse_kickoff(row.get(other_key))
            if parsed is not None:
                evaluated = parsed
                break
    if evaluated is None:
        raise NflTdError("TD_EVALUATION_TIME_UNKNOWN")
    if evaluated.tzinfo is None:
        evaluated = evaluated.replace(tzinfo=timezone.utc)
    return evaluated.astimezone(timezone.utc)


def phone_first_td_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    assessment = assess_first_td()
    evaluated = []
    for row in rows:
        evaluated.append({
            "status": "NO_MODEL_OR_MARKET",
            "reason": assessment["reason"],
            "blocker": "NO_DATA",
            "blocker_detail": assessment["reason"] + ": " + "; ".join(
                assessment.get("blockers", []))[:600],
            "sport": "NFL", "market": "FIRST_TD",
            "selection": row.get("side") or row.get("selection"),
            "player_name": row.get("player_name") or row.get("label"),
            "team": row.get("team"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
        })
    return evaluated


def phone_anytime_td_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    cache_dir: Any = None,
    opener: Callable | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Price (or fail-closed block) NFL ANYTIME_TD rows for the canonical card.

    Returns (evaluated, receipts).  History is loaded once per kickoff
    season set and cached within the call; cache hits never invoke the
    opener, so a fully cached run is offline-safe.
    """
    evaluated: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    histories: dict[tuple[int, ...], Any] = {}
    history_errors: dict[tuple[int, ...], str] = {}

    def history_for(kickoff):
        primary, _ = _history_seasons(kickoff)
        if primary in histories:
            return histories[primary], primary
        if primary in history_errors:
            raise NflTdError(history_errors[primary])
        try:
            history, used = _load_history(
                kickoff, cache_dir=cache_dir, opener=opener)
        except NflTdError as exc:
            history_errors[primary] = str(exc)
            raise
        histories[primary] = history
        receipts.append({
            "source": TD_SOURCE, "status": "NFLVERSE_TD_HISTORY_LOADED",
            "seasons_requested": list(primary),
            "seasons_loaded": list(used),
            "sources": [
                {"kind": pr.kind, "season": pr.season,
                 "sha256": pr.source_sha256}
                for pr in history["proofs"]],
        })
        return history, primary

    for row in rows:
        market = str(row.get("market") or "").upper()
        if market in FIRST_TD_MARKETS:
            evaluated.extend(phone_first_td_rows([row]))
            continue
        name = str(row.get("player_name") or row.get("label") or "").strip()
        team = team_abbreviation(row.get("team"))
        opponent = team_abbreviation(row.get("opponent"))
        kickoff = _parse_kickoff(row.get("kickoff") or row.get("commence_time")
                                  or row.get("start_time"))
        base = {"player_name": name, "team": team or str(row.get("team") or "")}

        def blocked(reason):
            out = blocked_anytime_td(player_name=name, team=base["team"],
                                     reason=str(reason)[:180])
            out["blocker"] = ("NO_PARTICIPATION"
                              if "TD_IDENTITY" in str(reason)
                              or "TD_TEAM_IDENTITY" in str(reason)
                              else "NO_DATA")
            out["quote_captured_at"] = row.get("quote_captured_at")
            out["kickoff"] = row.get("kickoff") or row.get("commence_time")
            return out

        if team is None or opponent is None:
            evaluated.append(blocked("TD_TEAM_IDENTITY_UNVERIFIED"))
            continue
        if kickoff is None:
            evaluated.append(blocked("TD_KICKOFF_UNPARSEABLE"))
            continue
        try:
            history, _ = history_for(kickoff)
        except NflTdError as exc:
            evaluated.append(blocked(exc))
            continue
        fixture, fixture_error = _resolve_fixture(
            history, team=team, opponent=opponent)
        if fixture_error is not None:
            evaluated.append(blocked(fixture_error))
            continue
        game_id, game_kickoff = fixture
        if now is not None and game_kickoff <= now:
            evaluated.append(blocked("TD_GAME_ALREADY_STARTED"))
            continue
        try:
            player_id = resolve_player_id(
                history, display_name=name, team=team, as_of=game_kickoff)
            priced = estimate_anytime_td(
                history, player_id=player_id, player_name=name, team=team,
                opponent=opponent, game_id=game_id, kickoff=game_kickoff)
        except NflTdError as exc:
            out = blocked(exc)
            out["game_id"] = game_id
            evaluated.append(out)
            continue

        side = str(row.get("side") or row.get("selection") or "YES").upper()
        if side not in ("YES", "NO"):
            evaluated.append(blocked("TD_SIDE_MUST_BE_YES_OR_NO"))
            continue
        try:
            eval_time = _evaluation_time(now, row)
        except NflTdError as exc:
            evaluated.append(blocked(exc))
            continue
        p_yes = float(priced["model_p"])
        model_row = {
            "sport": "NFL", "market": "ANYTIME_TD", "line": 0.5,
            "game_id": game_id, "selection": side,
            "player_id": player_id,
            "player_name": name, "team": team, "opponent": opponent,
            "kickoff_utc": game_kickoff.isoformat(),
            "as_of_utc": eval_time.isoformat(),
            "phase": "PREGAME", "status": "PRICED_RESEARCH",
            "market_blind": True, "model_source": TD_SOURCE,
            "estimate_p": p_yes if side == "YES" else 1.0 - p_yes,
            "push_p": 0.0, "validated_vs_close": False,
            "research_only": True,
        }
        quotes = []
        for other in rows:
            if str(other.get("market") or "").upper() not in TD_MARKETS:
                continue
            if (str(other.get("player_name") or other.get("label") or "").strip() != name
                    or team_abbreviation(other.get("team")) != team
                    or team_abbreviation(other.get("opponent")) != opponent):
                continue
            other_side = str(other.get("side") or other.get("selection")
                             or "").upper()
            odds = _odds(other.get("odds"))
            if other_side in ("YES", "NO") and odds is not None:
                quotes.append({
                    "sport": "NFL",
                    "book": str(other.get("book") or "DraftKings"),
                    "market": "ANYTIME_TD", "line": 0.5,
                    "game_id": game_id, "player_id": player_id,
                    "selection": other_side, "odds": odds,
                    "quote_captured_at": other.get("quote_captured_at"),
                })
        judged_payload = price_three_sport_research(
            [model_row], quotes, as_of=eval_time)
        judged_rows = judged_payload.get("rows") or []
        judged = judged_rows[0] if judged_rows else {
            "status": "NO_MODEL_OR_MARKET", "reason": "TD_BRIDGE_EMPTY"}
        if judged.get("status") == "NO_MODEL_OR_MARKET":
            out = blocked(judged.get("reason") or "TD_QUOTE_JUDGEMENT_FAILED")
            out["game_id"] = game_id
            out["model_probability"] = model_row["estimate_p"]
            evaluated.append(out)
            continue
        judged["source"] = TD_SOURCE
        judged["player_name"] = name
        judged["team"] = team
        judged["opponent"] = opponent
        judged["xtd"] = priced.get("xtd")
        judged["snap_share"] = priced.get("snap_share")
        judged["components"] = priced.get("components")
        judged["uncertainty_flags"] = priced.get("uncertainty_flags")
        judged["participation_status"] = (
            "SNAP_SHARE_VERIFIED_FROM_NFLVERSE_TRAILING_GAMES")
        judged["engine_evidence"] = priced.get("evidence")
        evaluated.append(judged)

    return evaluated, receipts
