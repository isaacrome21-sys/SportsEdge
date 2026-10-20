"""Provenance-checked adapters from actual MLB/NFL/CFB engines to DK research bridge.

Only *computed* probabilities from the existing MLB pitcher joint engine,
empirical batter game-log pricer, or attributed football simulation are
admitted. This module never reads a betting price or substitutes league
Poisson player priors. No OFFICIAL, Model_P, staking or authority. No betting
market is priced from unsupported inputs. Statcast and Next Gen remain
unwired.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence
from hashlib import sha256
import json

from sportsedge.pitcher_joint_engine import (
    price_pitcher_market, PitcherJointEngineError, PRICED_PITCHER_MARKETS,
    ENGINE_VERSION,
)
from sportsedge.mlb_batter_empirical import price_batter_market, BatterEmpiricalError
def derive_player_stat_market(*args, **kwargs):
    """Load optional football simulation dependencies only on football calls.

    The phone free MLB pitcher workflow deliberately has no numpy dependency.
    This wrapper remains patchable in football adapter regression tests.
    """
    from sportsedge.core.simulate.player_markets import derive_player_stat_market as derive
    return derive(*args, **kwargs)



def _timestamp(value: Any, field: str) -> datetime:
    try:
        when = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError(f"{field}_TIMEZONE_REQUIRED")
    return when.astimezone(timezone.utc)


def _text(value: Any, field: str) -> str:
    s = str(value or "").strip()
    if not s:
        raise ValueError(f"{field}_REQUIRED")
    return s


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}_NONFINITE")
    try:
        n = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field}_NONFINITE") from exc
    if not isfinite(n):
        raise ValueError(f"{field}_NONFINITE")
    return n


def _digest(value: Mapping) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _guard_time(*, kickoff_utc: str, as_of_utc: str, source_as_of_utc: str) -> tuple[str, str]:
    kickoff = _timestamp(kickoff_utc, "KICKOFF")
    current = _timestamp(as_of_utc, "MODEL_AS_OF")
    captured = _timestamp(source_as_of_utc, "SOURCE_AS_OF")
    if not captured <= current < kickoff:
        raise ValueError("NOT_STRICTLY_PRIOR_PREGAME_SOURCE")
    return current.isoformat(), kickoff.isoformat()


def _outcome(*, sport: str, game_id: str, market: str, selection: str,
             p: Any, push: Any, as_of_utc: str, kickoff_utc: str,
             model_source: str, model_input_hash: str,
             player_id: str | None = None, line: float | None = None,
             home_team: str | None = None, away_team: str | None = None) -> dict:
    win, mass = _num(p, "ENGINE_MODEL_P"), _num(push, "ENGINE_PUSH_P")
    if not 0 < win < 1 or not 0 <= mass < 1 or win + mass > 1 + 1e-9:
        raise ValueError("ENGINE_PROBABILITY_MASS_INVALID")
    side = _text(selection, "SIDE").upper()
    if side not in {"OVER", "UNDER", "HOME", "AWAY"}:
        raise ValueError("ENGINE_SIDE_UNSUPPORTED")
    row = {
        "sport": sport, "game_id": _text(game_id, "GAME_ID"),
        "market": _text(market, "MARKET").upper(), "selection": side,
        "estimate_p": win, "push_p": mass,
        "status": "PRICED_RESEARCH", "market_blind": True,
        "model_source": _text(model_source, "MODEL_SOURCE"),
        "model_input_hash": _text(model_input_hash, "INPUT_HASH"),
        "as_of_utc": as_of_utc, "kickoff_utc": kickoff_utc,
        "phase": "PREGAME", "validated_vs_close": False,
        "official_authority": False, "model_p_authority": False,
        "staking_authority": False, "research_only": True,
    }
    if player_id is not None:
        row["player_id"] = _text(player_id, "PLAYER_ID")
    if line is not None:
        row["line"] = _num(line, "LINE")
    if sport == "CFB":
        row["home_team"] = _text(home_team, "CFB_HOME_TEAM")
        row["away_team"] = _text(away_team, "CFB_AWAY_TEAM")
    elif home_team and away_team:
        row["home_team"], row["away_team"] = home_team, away_team
    return row


def _blocked(sport: str, game_id: str, market: str, selection: str,
             player_id: str | None, error: Exception) -> list[dict]:
    return [{
        "sport": sport, "game_id": game_id, "market": market,
        "selection": selection, "player_id": player_id,
        "status": "NO_MODEL_OR_MARKET", "reason": str(error)[:180],
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }]


def mlb_pitcher_to_bridge_rows(
    *, game_id: str, player_id: str, market: str, side: str, line: float,
    features: Mapping[str, Any], prior_start_times_utc: Sequence[str],
    source_as_of_utc: str, as_of_utc: str, kickoff_utc: str,
    starting_pitcher_verified: bool, home_team: str, away_team: str,
) -> list[dict]:
    """Genuine empirical-Bayes pitcher result with strictly prior timestamped starts.

    An independent verified upstream data collector must populate *features*
    and matching prior_start_times_utc, never the user's odds issue. This does
    not fetch or backfill features. No generic league priors are substituted.
    """
    try:
        if str(market).upper() not in PRICED_PITCHER_MARKETS or market.startswith("EITHER_"):
            raise ValueError("SINGLE_PITCHER_MARKET_REQUIRED")
        if starting_pitcher_verified is not True:
            raise ValueError("STARTER_UNVERIFIED")
        model_time, game_time = _guard_time(
            kickoff_utc=kickoff_utc, as_of_utc=as_of_utc,
            source_as_of_utc=source_as_of_utc)
        if not isinstance(features, Mapping):
            raise ValueError("REAL_PITCHER_HISTORY_REQUIRED")
        history = features.get("history_pool")
        # Do not infer missing prior starts from the market line.
        if not isinstance(history, (list, tuple)) or len(history) < 5:
            raise ValueError("FIVE_PRIOR_STARTS_REQUIRED")
        if not isinstance(prior_start_times_utc, (list, tuple)) or len(prior_start_times_utc) != len(history):
            raise ValueError("TIMESTAMP_EACH_PRIOR_START_REQUIRED")
        source_time = _timestamp(source_as_of_utc, "SOURCE_AS_OF")
        past = [_timestamp(t, "PRIOR_START") for t in prior_start_times_utc]
        if len(set(past)) != len(past) or not all(t < source_time for t in past):
            raise ValueError("HISTORY_LEAK_OR_DUPLICATE_START")
        market_input = {
            "game_id": _text(game_id, "GAME_ID"),
            "entity_id": _text(player_id, "PLAYER_ID"),
            "market": market.upper(), "side": side.upper(), "line": _num(line, "LINE"),
            "features": dict(features),
            "feature_source_hash": _digest({"features": features, "prior_start_times_utc": list(prior_start_times_utc),
                                            "source_as_of_utc": source_as_of_utc}),
        }
        outcome = price_pitcher_market(market_input)
        # Real engine returns model_p, not the nonexistent p / estimate_p.
        if outcome.get("engine_version") != ENGINE_VERSION:
            raise ValueError("PITCHER_ENGINE_VERSION_MISMATCH")
        return [_outcome(
            sport="MLB", game_id=game_id, market=market.upper(), selection=side,
            p=outcome["model_p"], push=outcome["push_p"],
            as_of_utc=model_time, kickoff_utc=game_time,
            model_source=f"mlb_pitcher_joint:{ENGINE_VERSION}",
            model_input_hash=outcome["model_input_hash"],
            player_id=player_id, line=line,
            home_team=home_team, away_team=away_team)]
    except (PitcherJointEngineError, ValueError, KeyError, TypeError, OverflowError) as exc:
        return _blocked("MLB", game_id, market, side, player_id, exc)


def mlb_batter_to_bridge_rows(
    *, game_id: str, player_id: str, market: str, side: str, line: float,
    features: Mapping[str, Any], prior_game_times_utc: Sequence[str],
    source_as_of_utc: str, as_of_utc: str, kickoff_utc: str,
    home_team: str, away_team: str,
    prior_game_ids: Sequence[str] | None = None,
) -> list[dict]:
    """Empirical batter result from verified prior game logs.

    An independent public StatsAPI collector must populate *features* and
    matching prior_game_times_utc. Lineup confirmation is not required for
    the research pricer (game log does not prove today's lineup). No league
    prior. Statcast not yet consumed.

    When the collector also supplies *prior_game_ids* (one gamePk per
    history row), duplicate detection keys on game identity: two distinct
    games sharing a start stamp are not a duplicate, and one game counted
    twice blocks even under two different stamps. The leak arm (every
    prior start strictly before the source as-of) applies either way.
    Without ids, the legacy timestamp-distinctness check is kept.
    """
    try:
        model_time, game_time = _guard_time(
            kickoff_utc=kickoff_utc, as_of_utc=as_of_utc,
            source_as_of_utc=source_as_of_utc)
        history = (features or {}).get("pa_history") if isinstance(features, Mapping) else None
        if not isinstance(history, (list, tuple)) or len(history) < 10:
            raise ValueError("TEN_PRIOR_GAMES_REQUIRED")
        try:
            total_pa = sum(_num(item["plate_appearances"], "PRIOR_PLATE_APPEARANCES")
                           for item in history)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("VERIFIED_PRIOR_PLATE_APPEARANCES_REQUIRED") from exc
        if total_pa < 20:
            raise ValueError("TWENTY_PRIOR_PLATE_APPEARANCES_REQUIRED")
        if not isinstance(prior_game_times_utc, (list, tuple)) or len(prior_game_times_utc) != len(history):
            raise ValueError("TIMESTAMP_EACH_PRIOR_GAME_REQUIRED")
        source_time = _timestamp(source_as_of_utc, "SOURCE_AS_OF")
        past = [_timestamp(t, "PRIOR_GAME") for t in prior_game_times_utc]
        if not all(t < source_time for t in past):
            raise ValueError("HISTORY_LEAK_OR_DUPLICATE_GAME")
        prior_ids: list[str] | None = None
        if prior_game_ids is not None:
            if (not isinstance(prior_game_ids, (list, tuple))
                    or len(prior_game_ids) != len(history)):
                raise ValueError("GAME_ID_EACH_PRIOR_GAME_REQUIRED")
            prior_ids = [_text(g, "PRIOR_GAME_ID") for g in prior_game_ids]
            if len(set(prior_ids)) != len(prior_ids):
                raise ValueError("HISTORY_LEAK_OR_DUPLICATE_GAME")
        elif len(set(past)) != len(past):
            raise ValueError("HISTORY_LEAK_OR_DUPLICATE_GAME")
        outcome = price_batter_market(
            market=market, side=side, line=line, pa_history=history)
        # An unsmoothed prior-game empirical proportion can be exactly 0
        # or 1 (particularly for rare HR and triples). Its win/loss/push
        # accounting still conserves mass: this is NOT a corrupt PMF.
        # No independently validated tail model exists to turn an
        # unobserved event into a current-price probability. Refuse by
        # the actual reason instead of the generic engine-mass error;
        # never clip, add pseudo-counts or infer an opposite quote.
        if (outcome["model_p"] in (0.0, 1.0)
                or outcome["push_p"] == 1.0):
            raise ValueError("EMPIRICAL_DEGENERATE_TAIL_NO_VALIDATED_MODEL")
        return [_outcome(
            sport="MLB", game_id=game_id, market=market.upper(), selection=side,
            p=outcome["model_p"], push=outcome["push_p"],
            as_of_utc=model_time, kickoff_utc=game_time,
            model_source=outcome["engine"],
            model_input_hash=_digest({
                "features": features,
                "prior_game_times_utc": list(prior_game_times_utc),
                **({"prior_game_ids": prior_ids} if prior_ids is not None else {}),
                "source_as_of_utc": source_as_of_utc}),
            player_id=player_id, line=line,
            home_team=home_team, away_team=away_team)]
    except (BatterEmpiricalError, ValueError, KeyError, TypeError) as exc:
        return _blocked("MLB", game_id, market, side, player_id, exc)


def football_player_stat_to_bridge_rows(
    *, sport: str, game_id: str, player_id: str, stat: str, line: float,
    side: str, paths: Sequence[Any], source_as_of_utc: str, as_of_utc: str,
    kickoff_utc: str, home_team: str, away_team: str,
    market_blind_simulation_verified: bool,
) -> list[dict]:
    """NFL/CFB readout from REAL attributed simulation paths, never fabricated."""
    sport = str(sport).upper()
    market = "PLAYER_" + str(stat).upper()
    try:
        if sport not in {"NFL", "CFB"}:
            raise ValueError("FOOTBALL_SPORT_INVALID")
        if market_blind_simulation_verified is not True:
            raise ValueError("MARKET_BLIND_PATHS_UNVERIFIED")
        model_time, game_time = _guard_time(
            kickoff_utc=kickoff_utc, as_of_utc=as_of_utc,
            source_as_of_utc=source_as_of_utc)
        if not isinstance(paths, (list, tuple)) or not paths:
            raise ValueError("REAL_ATTRIBUTED_PATHS_REQUIRED")
        # derive_player_stat_market independently verifies consistent game,
        # attributed-path types, player participation and settlement support.
        if any(p.base_path.game_id != str(game_id) for p in paths):
            raise ValueError("PATH_GAME_ID_MISMATCH")
        masses = derive_player_stat_market(
            paths, player_id=player_id, stat=stat, line=line)
        wanted = side.upper()
        if wanted not in ("OVER", "UNDER"):
            raise ValueError("FOOTBALL_SIDE_MUST_BE_OVER_UNDER")
        return [_outcome(
            sport=sport, game_id=game_id, market=market, selection=wanted,
            p=masses[wanted.lower()], push=masses["push"],
            as_of_utc=model_time, kickoff_utc=game_time,
            model_source=f"{sport.lower()}_shared_attributed_player_paths",
            # Source is a simulator-generated receipt, not a bet-line hash.
            model_input_hash=_digest({"game_id":game_id,"player_id":player_id,"stat":stat,
                                      "paths":len(paths),"as_of":source_as_of_utc}),
            player_id=player_id, line=line,
            home_team=home_team, away_team=away_team)]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return _blocked(sport, game_id, market, side, player_id, exc)
