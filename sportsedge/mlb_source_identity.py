"""Fail-closed identity checks for MLB pitcher/batter source rows.

Statcast/StatsAPI gameLog splits are fetched per player (or per team), so the
endpoint scopes identity. These checks close the remaining gaps:

* a split that CARRIES ``player.id`` / ``team.id`` must match the requested id
  (a mismatch means the payload is contaminated, so the whole response is refused);
* one ``gamePk`` may appear only once, unless the duplicate is byte-identical
  (identical duplicates are collapsed; conflicting duplicates are refused);
* a bound pregame record must match the target ``game_pk``, player id and team id.

Absent identity fields on a split are tolerated (endpoint-scoped) and never
inferred; absent fields on a bound record are refused.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .source_lineage import canonical_json_sha256


class MLBSourceIdentityError(ValueError):
    pass


def _strict_id(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise MLBSourceIdentityError(f"{name}_INVALID")
    if isinstance(value, int):
        out = value
    elif isinstance(value, str) and value.strip().isdigit():
        out = int(value.strip())
    else:
        raise MLBSourceIdentityError(f"{name}_INVALID")
    if out <= 0:
        raise MLBSourceIdentityError(f"{name}_INVALID")
    return out


def check_split_identity(split: Mapping[str, Any], *, expected_player_id: Any = None,
                         expected_team_id: Any = None) -> None:
    if not isinstance(split, Mapping):
        raise MLBSourceIdentityError("SPLIT_NOT_OBJECT")
    for key, expected, name in (("player", expected_player_id, "PLAYER"), ("team", expected_team_id, "TEAM")):
        if expected is None:
            continue
        want = _strict_id(expected, f"EXPECTED_{name}_ID")
        carried = split.get(key)
        if carried is None:
            continue
        if not isinstance(carried, Mapping) or carried.get("id") is None:
            raise MLBSourceIdentityError(f"SPLIT_{name}_IDENTITY_MALFORMED")
        if _strict_id(carried.get("id"), f"SPLIT_{name}_ID") != want:
            raise MLBSourceIdentityError(f"SPLIT_{name}_ID_MISMATCH")


def refuse_conflicting_game_pk(rows: Iterable[tuple[Any, Mapping[str, Any]]]) -> dict[int, Mapping[str, Any]]:
    """Map gamePk -> stat; identical duplicates collapse, conflicting ones refuse."""
    seen: dict[int, tuple[str, Mapping[str, Any]]] = {}
    for pk, stat in rows:
        if pk is None:
            continue
        key = _strict_id(pk, "GAME_PK")
        digest = canonical_json_sha256(dict(stat))
        prior = seen.get(key)
        if prior is not None and prior[0] != digest:
            raise MLBSourceIdentityError("GAME_PK_DUPLICATE_CONFLICTING_STATS")
        seen.setdefault(key, (digest, stat))
    return {k: v for k, (_, v) in seen.items()}


def bind_source_record(record: Mapping[str, Any], *, expected_game_pk: Any, expected_player_id: Any,
                       expected_team_id: Any) -> dict[str, int]:
    """Refuse a pregame player record unless game, player and team all bind."""
    if not isinstance(record, Mapping):
        raise MLBSourceIdentityError("RECORD_NOT_OBJECT")
    out = {}
    for field, expected, name in (("game_pk", expected_game_pk, "GAME_PK"),
                                  ("player_id", expected_player_id, "PLAYER_ID"),
                                  ("team_id", expected_team_id, "TEAM_ID")):
        want = _strict_id(expected, f"EXPECTED_{name}")
        if record.get(field) is None:
            raise MLBSourceIdentityError(f"RECORD_{name}_MISSING")
        if _strict_id(record.get(field), f"RECORD_{name}") != want:
            raise MLBSourceIdentityError(f"RECORD_{name}_MISMATCH")
        out[field] = want
    return out
