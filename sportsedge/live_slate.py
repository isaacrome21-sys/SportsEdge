"""Fail-closed live MLB slate assembly for validated hitter markets.

This module does not invent projections. It binds three independently sourced
objects: MLB schedule/lineup identity, a precomputed model-feature snapshot, and
a sportsbook quote. A candidate is emitted only when all identity fields match
and (when requested) the hitter is present in a confirmed batting order.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from math import isfinite
from typing import Any, Iterable, Mapping

from .identity_rng import build_hash
from .mlb_source import GameSnapshot


SUPPORTED_HITTER_MARKETS = {"HITS", "TOTAL_BASES"}


class LiveSlateError(ValueError):
    pass


@dataclass(frozen=True)
class TeamLineup:
    team_id: int
    side: str
    player_ids: tuple[int, ...]
    batting_slots: tuple[int, ...]
    confirmed: bool


@dataclass(frozen=True)
class LiveGame:
    game_pk: int
    away_team_id: int
    home_team_id: int
    away_lineup: TeamLineup
    home_lineup: TeamLineup


def lineup_from_rows(team_id: int, side: str, rows: Iterable[Mapping[str, Any]]) -> TeamLineup:
    if side not in ("away", "home"):
        raise LiveSlateError("side must be away or home")
    players: list[int] = []
    slots: list[int] = []
    primary_slots: set[int] = set()
    seen_players: set[int] = set()
    for row in rows:
        pid = row.get("player_id")
        slot = row.get("slot")
        seq = row.get("sequence", 0)
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise LiveSlateError("lineup row has invalid player_id")
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 9:
            raise LiveSlateError("lineup row has invalid batting slot")
        if pid in seen_players:
            raise LiveSlateError("duplicate player_id in lineup rows")
        seen_players.add(pid)
        players.append(pid)
        slots.append(slot)
        if seq == 0:
            primary_slots.add(slot)
    confirmed = primary_slots == set(range(1, 10))
    return TeamLineup(int(team_id), side, tuple(players), tuple(slots), confirmed)


def make_live_game(snapshot: GameSnapshot, away_rows: Iterable[Mapping[str, Any]], home_rows: Iterable[Mapping[str, Any]]) -> LiveGame:
    return LiveGame(
        game_pk=snapshot.game_pk,
        away_team_id=snapshot.away_id,
        home_team_id=snapshot.home_id,
        away_lineup=lineup_from_rows(snapshot.away_id, "away", away_rows),
        home_lineup=lineup_from_rows(snapshot.home_id, "home", home_rows),
    )


def _finite_number(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise LiveSlateError(f"{name} must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise LiveSlateError(f"{name} must be finite numeric") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise LiveSlateError(f"{name} out of range")
    return out


def _clean_pa_pool(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value:
        raise LiveSlateError("pa_pool must be a non-empty list/tuple")
    out: list[int] = []
    for x in value:
        if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 9:
            raise LiveSlateError("pa_pool must contain integer PA counts in [0,9]")
        out.append(x)
    return out


def _feature_payload(market: str, feature_row: Mapping[str, Any]) -> dict[str, Any]:
    common = {"game_pk", "player_id", "team_id", "market"}
    if feature_row.get("market") != market:
        raise LiveSlateError("feature market does not match candidate market")

    if market == "HITS":
        expected = {"b_rate", "p_rate", "pa_pool"}
        extra = set(feature_row) - common - expected
        missing = expected - set(feature_row)
        if extra:
            raise LiveSlateError(f"unexpected HITS feature fields: {sorted(extra)}")
        if missing:
            raise LiveSlateError(f"missing HITS feature fields: {sorted(missing)}")
        b_rate = _finite_number("b_rate", feature_row["b_rate"], 0, 1)
        p_rate = _finite_number("p_rate", feature_row["p_rate"], 0, 1)
        return {"b_rate": b_rate, "p_rate": p_rate, "pa_pool": _clean_pa_pool(feature_row["pa_pool"])}

    if market == "TOTAL_BASES":
        expected = {"rates", "p_h", "p_hr", "park", "pa_pool"}
        extra = set(feature_row) - common - expected
        missing = expected - set(feature_row)
        if extra:
            raise LiveSlateError(f"unexpected TOTAL_BASES feature fields: {sorted(extra)}")
        if missing:
            raise LiveSlateError(f"missing TOTAL_BASES feature fields: {sorted(missing)}")
        rates = feature_row["rates"]
        if not isinstance(rates, Mapping) or set(rates) != {"s", "d", "t", "hr"}:
            raise LiveSlateError("TOTAL_BASES rates must contain exactly s,d,t,hr")
        clean_rates = {k: _finite_number(f"rates.{k}", rates[k], 0, 1) for k in ("s", "d", "t", "hr")}
        if sum(clean_rates.values()) >= 1:
            raise LiveSlateError("TOTAL_BASES hit-event rates must sum to < 1")
        return {
            "rates": clean_rates,
            "p_h": _finite_number("p_h", feature_row["p_h"], 1e-8, 1),
            "p_hr": _finite_number("p_hr", feature_row["p_hr"], 1e-8, 1),
            "park": _finite_number("park", feature_row["park"], 0.01, 10),
            "pa_pool": _clean_pa_pool(feature_row["pa_pool"]),
        }

    raise LiveSlateError(f"unsupported hitter market: {market}")


def _player_lineup_status(game: LiveGame, player_id: int) -> str:
    in_away = player_id in game.away_lineup.player_ids
    in_home = player_id in game.home_lineup.player_ids
    if in_away and in_home:
        raise LiveSlateError("player appears in both lineups")
    if in_away:
        return "CONFIRMED" if game.away_lineup.confirmed else "PROJECTED"
    if in_home:
        return "CONFIRMED" if game.home_lineup.confirmed else "PROJECTED"
    raise LiveSlateError("player not present in MLB lineup snapshot")


def assemble_hitter_candidate(
    *,
    game: LiveGame,
    market: str,
    feature_row: Mapping[str, Any],
    quote: Mapping[str, Any],
    require_confirmed_lineup: bool = True,
) -> dict[str, Any]:
    """Create one canonical runtime candidate or fail closed.

    The quote remains outside Model_Input. Sportsbook odds never participate in
    feature construction or RNG identity.
    """
    if market not in SUPPORTED_HITTER_MARKETS:
        raise LiveSlateError(f"unsupported hitter market: {market}")
    if type(require_confirmed_lineup) is not bool:
        raise LiveSlateError("require_confirmed_lineup must be boolean")

    game_pk = feature_row.get("game_pk")
    player_id = feature_row.get("player_id")
    if game_pk != game.game_pk:
        raise LiveSlateError("feature game_pk does not match live game")
    if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0:
        raise LiveSlateError("feature player_id invalid")

    lineup_status = _player_lineup_status(game, player_id)
    if require_confirmed_lineup and lineup_status != "CONFIRMED":
        raise LiveSlateError("confirmed MLB batting order required")

    q_game = quote.get("game_id")
    q_market = quote.get("market")
    q_entity = quote.get("entity_id")
    if str(q_game) != str(game.game_pk) or q_market != market or str(q_entity) != str(player_id):
        raise LiveSlateError("quote identity does not match feature/live identity")
    line = _finite_number("line", quote.get("line"))
    side = quote.get("side")
    if side not in ("OVER", "UNDER"):
        raise LiveSlateError("quote side must be OVER or UNDER")

    features = _feature_payload(market, feature_row)
    feature_json = json.dumps(features, sort_keys=True, separators=(",", ":"))
    identity = build_hash([
        str(game.game_pk), market, str(player_id), format(line, ".12g"), side,
        lineup_status, feature_json,
    ])

    model_input = {
        "game_id": str(game.game_pk),
        "market": market,
        "entity_id": str(player_id),
        "line": quote.get("line"),
        "side": side,
        "build_hash": identity,
        "lineup_status": lineup_status,
        "require_confirmed_lineup": require_confirmed_lineup,
        "features": features,
    }
    clean_quote = dict(quote)
    clean_quote["game_id"] = str(game.game_pk)
    clean_quote["entity_id"] = str(player_id)
    return {"model_input": model_input, "quote": clean_quote}


def live_game_to_dict(game: LiveGame) -> dict[str, Any]:
    return asdict(game)
