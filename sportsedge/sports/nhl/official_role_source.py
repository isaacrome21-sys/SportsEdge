from __future__ import annotations

"""Build NHL skater role observations from official Gamecenter sources.

Full-game skater shots come from the official boxscore.  Regulation goal,
primary-assist and secondary-assist identities come from official play-by-play
``goal`` events in periods 1-3.  The PBP fields are publicly documented/observed
as ``scoringPlayerId``, ``assist1PlayerId`` and ``assist2PlayerId``.

Absolute event UTC is not required for this completed-game role history.  This
module therefore does not weaken the stricter shot/xG event-time contract in
``official_pbp_source.py``.  Retrieval timestamps and raw payload hashes are
preserved, and the resulting rows are development history rather than
retroactive betting evidence.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from .official_boxscore_source import BOXSCORE_ENDPOINT
from .official_pbp_source import OFFICIAL_PBP_PREFIX
from .role_history import NHLPlayerGameRoleObservation

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FINAL_STATES = frozenset({"OFF", "FINAL"})


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _valid_sha(value: str, field: str) -> str:
    text = str(value).lower()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"valid {field} SHA-256 required")
    return text


def _team_id(payload: Mapping[str, Any], side: str) -> str:
    team = payload.get(f"{side}Team")
    if not isinstance(team, Mapping):
        raise ValueError(f"official boxscore missing {side}Team")
    team_id = str(team.get("id") or "").strip()
    if not team_id:
        raise ValueError(f"official boxscore missing {side} team id")
    return team_id


def _skater_shots(boxscore_payload: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, int]]:
    """Return skater->team and skater->full-game SOG from official boxscore."""
    boxscore = boxscore_payload.get("boxscore")
    if not isinstance(boxscore, Mapping):
        raise ValueError("official boxscore object required")
    stats = boxscore.get("playerByGameStats")
    if not isinstance(stats, Mapping):
        raise ValueError("official boxscore playerByGameStats required")
    player_team: dict[str, str] = {}
    shots: dict[str, int] = {}
    for side in ("home", "away"):
        team_id = _team_id(boxscore_payload, side)
        team_stats = stats.get(f"{side}Team")
        if not isinstance(team_stats, Mapping):
            raise ValueError(f"playerByGameStats missing {side}Team")
        for group in ("forwards", "defense"):
            rows = team_stats.get(group)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
                raise ValueError(f"playerByGameStats {side}Team.{group} must be a list")
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("skater row must be a mapping")
                player_id = str(row.get("playerId") or "").strip()
                if not player_id or player_id in player_team:
                    raise ValueError("unique skater playerId required")
                try:
                    sog = int(row.get("shots", 0))
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid skater shots") from exc
                if sog < 0:
                    raise ValueError("skater shots must be nonnegative")
                player_team[player_id] = team_id
                shots[player_id] = sog
    if not player_team:
        raise ValueError("official boxscore contains no skaters")
    return player_team, shots


def build_official_player_role_observations(
    *,
    boxscore_payload: Mapping[str, Any],
    pbp_payload: Mapping[str, Any],
    boxscore_captured_at: str,
    pbp_captured_at: str,
    boxscore_raw_sha256: str,
    pbp_raw_sha256: str,
    boxscore_source_uri: str | None = None,
    pbp_source_uri: str | None = None,
    source_version: str = "nhl-web-api-v1",
) -> tuple[NHLPlayerGameRoleObservation, ...]:
    """Normalize one completed game's skater SOG and regulation event roles."""
    if not isinstance(boxscore_payload, Mapping) or not isinstance(pbp_payload, Mapping):
        raise ValueError("official boxscore and PBP payloads must be mappings")
    box_game = str(boxscore_payload.get("id") or "").strip()
    pbp_game = str(pbp_payload.get("id") or pbp_payload.get("gameId") or "").strip()
    if not box_game or box_game != pbp_game:
        raise ValueError("official boxscore/PBP game identity mismatch")
    state = str(boxscore_payload.get("gameState") or "").strip().upper()
    if state not in _FINAL_STATES:
        raise ValueError("official boxscore must be final/off")
    puck_drop = str(boxscore_payload.get("startTimeUTC") or "").strip()
    if not puck_drop:
        raise ValueError("official boxscore startTimeUTC required")
    puck = _utc(puck_drop, "startTimeUTC")
    box_cap = _utc(boxscore_captured_at, "boxscore_captured_at")
    pbp_cap = _utc(pbp_captured_at, "pbp_captured_at")
    if box_cap <= puck or pbp_cap <= puck:
        raise ValueError("completed role sources must be retrieved after puck drop")

    box_sha = _valid_sha(boxscore_raw_sha256, "boxscore")
    pbp_sha = _valid_sha(pbp_raw_sha256, "PBP")
    box_uri = boxscore_source_uri or BOXSCORE_ENDPOINT.format(game_id=box_game)
    expected_box = BOXSCORE_ENDPOINT.format(game_id=box_game)
    if box_uri != expected_box:
        raise ValueError("official NHL Gamecenter boxscore URI required")
    pbp_uri = pbp_source_uri or f"{OFFICIAL_PBP_PREFIX}{box_game}/play-by-play"
    expected_pbp = f"{OFFICIAL_PBP_PREFIX}{box_game}/play-by-play"
    if pbp_uri != expected_pbp:
        raise ValueError("official NHL Gamecenter play-by-play URI required")
    if not str(source_version).strip():
        raise ValueError("source_version required")

    player_team, shots = _skater_shots(boxscore_payload)
    home_id = _team_id(boxscore_payload, "home")
    away_id = _team_id(boxscore_payload, "away")
    if home_id == away_id:
        raise ValueError("distinct home/away team ids required")

    goals = {player: 0 for player in player_team}
    primary = {player: 0 for player in player_team}
    secondary = {player: 0 for player in player_team}
    plays = pbp_payload.get("plays")
    if not isinstance(plays, Sequence) or isinstance(plays, (str, bytes, bytearray)):
        raise ValueError("official NHL PBP plays required")

    for play in plays:
        if not isinstance(play, Mapping) or str(play.get("typeDescKey") or "") != "goal":
            continue
        descriptor = play.get("periodDescriptor") or {}
        if not isinstance(descriptor, Mapping):
            raise ValueError("goal periodDescriptor must be a mapping")
        try:
            period = int(descriptor.get("number") or play.get("period") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("goal period number required") from exc
        if period < 1:
            raise ValueError("positive goal period required")
        if period > 3:
            continue
        details = play.get("details") or {}
        if not isinstance(details, Mapping):
            raise ValueError("goal details must be a mapping")
        owner = str(details.get("eventOwnerTeamId") or "").strip()
        if owner not in {home_id, away_id}:
            raise ValueError("goal eventOwnerTeamId must match official teams")
        scorer = str(details.get("scoringPlayerId") or "").strip()
        if not scorer or scorer not in player_team or player_team[scorer] != owner:
            raise ValueError("regulation scorer must be an official skater on scoring team")
        goals[scorer] += 1
        for key, target in (("assist1PlayerId", primary), ("assist2PlayerId", secondary)):
            value = details.get(key)
            if value in (None, ""):
                continue
            player_id = str(value)
            # Goalie assists are valid NHL events but this role model is skater-only.
            if player_id not in player_team:
                continue
            if player_team[player_id] != owner or player_id == scorer:
                raise ValueError("goal assist identity/team mismatch")
            target[player_id] += 1

    settled = max(box_cap, pbp_cap).isoformat()
    joint_sha = sha256(
        json.dumps(
            {
                "game_id": box_game,
                "boxscore_raw_sha256": box_sha,
                "pbp_raw_sha256": pbp_sha,
                "boxscore_captured_at": box_cap.isoformat(),
                "pbp_captured_at": pbp_cap.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    source = f"{box_uri}+{pbp_uri}"
    version = f"{source_version}:joint={joint_sha}"
    return tuple(
        NHLPlayerGameRoleObservation(
            game_id=box_game,
            player_id=player_id,
            team_id=player_team[player_id],
            puck_drop=puck.isoformat(),
            settled_at=settled,
            source=source,
            source_version=version,
            shots_on_goal=shots[player_id],
            goals=goals[player_id],
            primary_assists=primary[player_id],
            secondary_assists=secondary[player_id],
        )
        for player_id in sorted(player_team)
    )


__all__ = ["build_official_player_role_observations"]
