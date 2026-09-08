"""Runtime verification of acquisition-stamped MLB wager identity.

This module is deliberately verification-only. It must never create event,
game-number, team, player, multi-entity, or N-way outcome identity from the
canonical schedule or from model inputs. Those identities must already exist on
the normalized quote because they were stamped by the acquisition adapter.

The immutable MLB event id is sufficient to identify an ordinary single game.
`game_number` is required only when the canonical schedule supplies doubleheader
metadata; it is never fabricated as 1 merely to satisfy a validator.
"""
from __future__ import annotations

from typing import Any, Mapping

from .mlb_market_binding_v13 import (
    BATTER,
    FIELD,
    MARKET_BINDINGS,
    MULTI_PITCHER,
    PITCHER,
    TEAM,
    BindingError,
    runtime_quote_binding_row,
    validate_quote_binding,
)


def _required_text(row: Mapping[str, Any], field: str, market: str) -> str:
    value = row.get(field)
    if value is None or not str(value).strip():
        raise BindingError(f"RUNTIME_SOURCE_IDENTITY_MISSING:{market}:{field}")
    return str(value).strip()


def verify_runtime_binding_context(quote: Mapping[str, Any], game: Any) -> dict[str, Any]:
    """Verify quote-origin identity against the already-resolved canonical MLB game.

    Returns a shallow copy only after all checks pass. No missing field is filled.
    """
    if not isinstance(quote, Mapping):
        raise BindingError("RUNTIME_QUOTE_NOT_MAPPING")
    out = dict(quote)
    market = str(out.get("market") or "").upper()
    spec = MARKET_BINDINGS.get(market)
    if spec is None:
        raise BindingError(f"UNKNOWN_MARKET_ID:{market!r}")

    event_id = _required_text(out, "event_id", market)
    if event_id != str(game.game_pk):
        raise BindingError(f"RUNTIME_EVENT_ID_MISMATCH:{market}:{event_id}!={game.game_pk}")

    canonical_game_number = getattr(game, "game_number", None)
    quote_game_number = out.get("game_number")
    if canonical_game_number is not None:
        if quote_game_number is None:
            raise BindingError(f"RUNTIME_SOURCE_IDENTITY_MISSING:{market}:game_number")
        if quote_game_number != canonical_game_number:
            raise BindingError(
                f"RUNTIME_GAME_NUMBER_MISMATCH:{market}:"
                f"{quote_game_number!r}!={canonical_game_number!r}"
            )
    elif quote_game_number not in (None, 1):
        raise BindingError(
            f"RUNTIME_GAME_NUMBER_MISMATCH:{market}:{quote_game_number!r}!=ordinary"
        )

    home = _required_text(out, "event_home_team_id", market)
    away = _required_text(out, "event_away_team_id", market)
    if home != str(game.home_team_id):
        raise BindingError(f"RUNTIME_HOME_TEAM_MISMATCH:{market}:{home}!={game.home_team_id}")
    if away != str(game.away_team_id):
        raise BindingError(f"RUNTIME_AWAY_TEAM_MISMATCH:{market}:{away}!={game.away_team_id}")

    if spec.entity_type == TEAM:
        team_id = _required_text(out, "team_id", market)
        entity_id = _required_text(out, "entity_id", market)
        if team_id != entity_id:
            raise BindingError(f"RUNTIME_TEAM_ENTITY_MISMATCH:{market}:{team_id}!={entity_id}")
    elif spec.entity_type in {BATTER, PITCHER}:
        _required_text(out, "entity_id", market)
        if (
            out.get("player_id") not in (None, "")
            and str(out["player_id"]).strip() != str(out["entity_id"]).strip()
        ):
            raise BindingError(f"RUNTIME_PLAYER_ENTITY_MISMATCH:{market}")
    elif spec.entity_type == MULTI_PITCHER:
        ids = out.get("entity_ids")
        if not isinstance(ids, (list, tuple)) or len(ids) != 2:
            raise BindingError(f"RUNTIME_SOURCE_IDENTITY_MISSING:{market}:entity_ids")
        canonical = "|".join(str(x).strip() for x in ids)
        if canonical != _required_text(out, "entity_id", market):
            raise BindingError(f"RUNTIME_MULTI_ENTITY_MISMATCH:{market}")
    elif spec.entity_type == FIELD:
        _required_text(out, "outcome_id", market)
        side = str(out.get("side") or "").upper()
        if side == "PLAYER":
            player = _required_text(out, "outcome_player_id", market)
            if player != _required_text(out, "entity_id", market):
                raise BindingError(f"RUNTIME_NWAY_PLAYER_ENTITY_MISMATCH:{market}")

    validate_quote_binding(runtime_quote_binding_row(out))
    return out
