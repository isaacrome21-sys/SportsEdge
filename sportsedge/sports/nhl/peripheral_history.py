from __future__ import annotations

"""Official NHL boxscore history for player blocks and hits.

The public Gamecenter boxscore exposes per-skater ``hits`` and ``blockedShots``
inside ``playerByGameStats``.  This module normalizes those completed-game rows
and fits transparent empirical team/player weights for the coherent peripheral
engine.  Historical backfills are development inputs captured when retrieved;
they are not retroactive betting evidence.

Schema references used for field verification (implementation is original):
- pseudo-r/Public-NHL-API ``docs/web-api/games.md`` (MIT)
- FHFHockey-dev/fhfhockey.com ``web/lib/NHL/types.ts`` (public GitHub schema example)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .official_boxscore_source import BOXSCORE_ENDPOINT
from .peripheral_props import NHLPeripheralRole, NHLTeamPeripheralParameters

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


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if out < 0:
        raise ValueError(f"{field} must be nonnegative")
    return out


def _toi_seconds(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid skater toi:{text}")
    try:
        minute, second = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"invalid skater toi:{text}") from exc
    if minute < 0 or second < 0 or second >= 60:
        raise ValueError(f"invalid skater toi:{text}")
    return minute * 60 + second


@dataclass(frozen=True)
class NHLPlayerPeripheralObservation:
    game_id: str
    player_id: str
    team_id: str
    team_side: str
    start_time_utc: str
    captured_at: str
    hits: int
    blocks: int
    toi_seconds: int
    source_uri: str
    source_raw_sha256: str
    source_version: str

    def __post_init__(self) -> None:
        if not all((self.game_id, self.player_id, self.team_id, self.source_uri, self.source_version)):
            raise ValueError("peripheral observation identity/provenance required")
        if self.team_side not in {"HOME", "AWAY"}:
            raise ValueError("team_side must be HOME or AWAY")
        if _utc(self.captured_at, "captured_at") <= _utc(self.start_time_utc, "start_time_utc"):
            raise ValueError("completed peripheral receipt must postdate puck drop")
        if min(self.hits, self.blocks, self.toi_seconds) < 0:
            raise ValueError("peripheral counts/TOI must be nonnegative")
        expected = BOXSCORE_ENDPOINT.format(game_id=self.game_id)
        if self.source_uri != expected:
            raise ValueError("official NHL Gamecenter boxscore URI required")
        if not _SHA256.fullmatch(self.source_raw_sha256.lower()):
            raise ValueError("valid raw boxscore SHA-256 required")


def extract_player_peripheral_observations(
    payload: Mapping[str, Any],
    *,
    captured_at: str,
    raw_sha256: str,
    source_uri: str | None = None,
    source_version: str = "nhl-web-api-v1",
) -> tuple[NHLPlayerPeripheralObservation, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("official boxscore payload must be a mapping")
    game_id = str(payload.get("id") or "").strip()
    if not game_id:
        raise ValueError("official boxscore game id required")
    uri = source_uri or BOXSCORE_ENDPOINT.format(game_id=game_id)
    if uri != BOXSCORE_ENDPOINT.format(game_id=game_id):
        raise ValueError("official NHL Gamecenter boxscore URI required")
    if not _SHA256.fullmatch(str(raw_sha256).lower()):
        raise ValueError("valid raw boxscore SHA-256 required")
    state = str(payload.get("gameState") or "").strip().upper()
    if state not in _FINAL_STATES:
        raise ValueError("official boxscore is not final/off")
    start_time = str(payload.get("startTimeUTC") or "").strip()
    if not start_time:
        raise ValueError("official boxscore startTimeUTC required")
    if _utc(captured_at, "captured_at") <= _utc(start_time, "startTimeUTC"):
        raise ValueError("completed peripheral receipt must postdate puck drop")

    boxscore = payload.get("boxscore")
    if not isinstance(boxscore, Mapping):
        raise ValueError("official boxscore object required")
    player_stats = boxscore.get("playerByGameStats")
    if not isinstance(player_stats, Mapping):
        raise ValueError("official boxscore playerByGameStats required")

    out: list[NHLPlayerPeripheralObservation] = []
    seen: set[tuple[str, str]] = set()
    for side_key, team_side in (("home", "HOME"), ("away", "AWAY")):
        team = payload.get(f"{side_key}Team")
        if not isinstance(team, Mapping):
            raise ValueError(f"official boxscore missing {side_key}Team")
        team_id = str(team.get("id") or "").strip()
        if not team_id:
            raise ValueError(f"official boxscore missing {side_key} team id")
        stat_team = player_stats.get(f"{side_key}Team")
        if not isinstance(stat_team, Mapping):
            raise ValueError(f"playerByGameStats missing {side_key}Team")
        for group in ("forwards", "defense"):
            rows = stat_team.get(group)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
                raise ValueError(f"playerByGameStats {side_key}Team.{group} must be a list")
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("skater boxscore row must be a mapping")
                player_id = str(row.get("playerId") or "").strip()
                if not player_id:
                    raise ValueError("skater boxscore row missing playerId")
                identity = (team_id, player_id)
                if identity in seen:
                    raise ValueError("duplicate skater in official boxscore")
                seen.add(identity)
                out.append(NHLPlayerPeripheralObservation(
                    game_id=game_id,
                    player_id=player_id,
                    team_id=team_id,
                    team_side=team_side,
                    start_time_utc=_utc(start_time, "startTimeUTC").isoformat(),
                    captured_at=_utc(captured_at, "captured_at").isoformat(),
                    hits=_nonnegative_int(row.get("hits", 0), "hits"),
                    blocks=_nonnegative_int(row.get("blockedShots", 0), "blockedShots"),
                    toi_seconds=_toi_seconds(row.get("toi")),
                    source_uri=uri,
                    source_raw_sha256=str(raw_sha256).lower(),
                    source_version=str(source_version),
                ))
    return tuple(sorted(out, key=lambda r: (r.team_id, r.player_id)))


def peripheral_history_sha256(rows: Sequence[NHLPlayerPeripheralObservation]) -> str:
    payload = [r.__dict__ for r in sorted(rows, key=lambda r: (r.start_time_utc, r.game_id, r.team_id, r.player_id))]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _eligible(
    observations: Sequence[NHLPlayerPeripheralObservation],
    *,
    cutoff: str,
    team_id: str,
) -> tuple[NHLPlayerPeripheralObservation, ...]:
    cut = _utc(cutoff, "cutoff")
    return tuple(sorted(
        (r for r in observations if r.team_id == team_id and _utc(r.start_time_utc, "start_time_utc") < cut),
        key=lambda r: (_utc(r.start_time_utc, "start_time_utc"), r.game_id, r.player_id),
    ))


def fit_team_peripheral_parameters(
    observations: Sequence[NHLPlayerPeripheralObservation],
    *,
    cutoff: str,
    team_id: str,
    version: str,
    min_games: int = 10,
) -> NHLTeamPeripheralParameters:
    if not team_id or not version or min_games < 1:
        raise ValueError("team_id/version and positive min_games required")
    rows = _eligible(observations, cutoff=cutoff, team_id=team_id)
    by_game: dict[str, list[NHLPlayerPeripheralObservation]] = {}
    for row in rows:
        by_game.setdefault(row.game_id, []).append(row)
    if len(by_game) < min_games:
        raise ValueError("insufficient historical team peripheral games")
    blocks = [sum(r.blocks for r in game_rows) for game_rows in by_game.values()]
    hits = [sum(r.hits for r in game_rows) for game_rows in by_game.values()]
    digest = peripheral_history_sha256(rows)
    params = NHLTeamPeripheralParameters(
        version=version,
        expected_blocks=sum(blocks) / len(blocks),
        expected_hits=sum(hits) / len(hits),
        source="official-nhl-gamecenter-boxscores",
        history_sha256=digest,
    )
    params.validate()
    return params


def fit_empirical_peripheral_roles(
    observations: Sequence[NHLPlayerPeripheralObservation],
    *,
    cutoff: str,
    team_id: str,
    team_side: str,
    active_player_ids: Sequence[str],
    version: str,
    min_games: int = 3,
    lineup_status: str = "PROJECTED",
    require_complete: bool = True,
) -> tuple[NHLPeripheralRole, ...]:
    if team_side not in {"HOME", "AWAY"} or lineup_status not in {"CONFIRMED", "PROJECTED"}:
        raise ValueError("invalid team_side or lineup_status")
    if not team_id or not version or min_games < 1:
        raise ValueError("team_id/version and positive min_games required")
    active = tuple(dict.fromkeys(str(x) for x in active_player_ids if str(x)))
    if not active:
        raise ValueError("active_player_ids required")
    rows = _eligible(observations, cutoff=cutoff, team_id=team_id)
    digest = peripheral_history_sha256(rows)
    by_player: dict[str, list[NHLPlayerPeripheralObservation]] = {}
    for row in rows:
        if row.player_id in active:
            by_player.setdefault(row.player_id, []).append(row)
    missing = [p for p in active if len(by_player.get(p, ())) < min_games]
    if require_complete and missing:
        raise ValueError("insufficient peripheral history for active players:" + ",".join(sorted(missing)))
    roles: list[NHLPeripheralRole] = []
    for player_id in sorted(active):
        history = by_player.get(player_id, [])
        if len(history) < min_games:
            continue
        roles.append(NHLPeripheralRole(
            player_id=player_id,
            team=team_side,
            captured_at=_utc(cutoff, "cutoff").isoformat(),
            source="official-nhl-gamecenter-boxscores",
            version=f"{version}:{digest}",
            block_weight=sum(r.blocks for r in history) / len(history),
            hit_weight=sum(r.hits for r in history) / len(history),
            lineup_status=lineup_status,
        ))
    if not roles:
        raise ValueError("no eligible peripheral roles")
    if not math.isfinite(sum(r.block_weight + r.hit_weight for r in roles)):
        raise ValueError("nonfinite peripheral role weights")
    return tuple(roles)


__all__ = [
    "NHLPlayerPeripheralObservation",
    "extract_player_peripheral_observations",
    "peripheral_history_sha256",
    "fit_team_peripheral_parameters",
    "fit_empirical_peripheral_roles",
]
