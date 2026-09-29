from __future__ import annotations

"""Fail-closed official NHL completed-game boxscore receipts.

The official ``api-web.nhle.com`` Gamecenter boxscore is used only as a public
historical result/stat source.  A receipt binds the exact raw HTTP bytes by
SHA-256 and records the real retrieval timestamp.  Backfilled receipts are
therefore development data captured when they were actually retrieved; they do
not retroactively become point-in-time evidence for old betting decisions.

Endpoint/schema references (documentation only; implementation here is
original):
- pseudo-r/Public-NHL-API ``docs/web-api/games.md`` (MIT)
- Zmalski/NHL-API-Reference ``README.md`` (MIT)
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Sequence

NHL_WEB_API_BASE = "https://api-web.nhle.com"
BOXSCORE_ENDPOINT = NHL_WEB_API_BASE + "/v1/gamecenter/{game_id}/boxscore"
SOURCE_REFERENCES = (
    "pseudo-r/Public-NHL-API:docs/web-api/games.md",
    "Zmalski/NHL-API-Reference:README.md",
)
_FINAL_STATES = frozenset({"OFF", "FINAL"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def _power_play(value: Any) -> tuple[int, int] | None:
    """Parse the official ``goals/opportunities`` display string when present."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid powerPlayConversion:{text}")
    goals = _nonnegative_int(parts[0], "powerPlayConversion goals")
    opportunities = _nonnegative_int(parts[1], "powerPlayConversion opportunities")
    if goals > opportunities:
        raise ValueError("power-play goals cannot exceed opportunities")
    return goals, opportunities


def _toi_seconds(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid goalie toi:{text}")
    try:
        minute, second = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"invalid goalie toi:{text}") from exc
    if minute < 0 or second < 0 or second >= 60:
        raise ValueError(f"invalid goalie toi:{text}")
    return minute * 60 + second


def _save_shots_against(value: Any) -> tuple[int, int] | None:
    """Parse official goalie ``saveShotsAgainst`` strings such as ``24/27``."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split("/")
    if len(parts) != 2:
        raise ValueError(f"invalid saveShotsAgainst:{text}")
    saves = _nonnegative_int(parts[0], "goalie saves")
    shots = _nonnegative_int(parts[1], "goalie shots against")
    if saves > shots:
        raise ValueError("goalie saves cannot exceed shots against")
    return saves, shots


@dataclass(frozen=True)
class NHLGoalieBoxscore:
    player_id: str
    goals_against: int
    saves: int | None
    shots_against: int | None
    toi_seconds: int | None

    def __post_init__(self) -> None:
        if not self.player_id:
            raise ValueError("goalie player_id required")
        if self.goals_against < 0:
            raise ValueError("goalie goals_against must be nonnegative")
        if (self.saves is None) != (self.shots_against is None):
            raise ValueError("goalie saves/shots_against must be present together")
        if self.saves is not None and self.shots_against is not None:
            if min(self.saves, self.shots_against) < 0 or self.saves > self.shots_against:
                raise ValueError("invalid goalie save/shot counts")
        if self.toi_seconds is not None and self.toi_seconds < 0:
            raise ValueError("goalie toi must be nonnegative")


@dataclass(frozen=True)
class NHLOfficialCompletedGame:
    game_id: str
    season: str
    game_type: int
    game_date: str
    start_time_utc: str
    captured_at: str
    game_state: str
    away_team_id: str
    home_team_id: str
    away_abbrev: str
    home_abbrev: str
    away_regulation_goals: int
    home_regulation_goals: int
    away_final_goals: int
    home_final_goals: int
    away_sog: int
    home_sog: int
    away_pp_goals: int | None
    away_pp_opportunities: int | None
    home_pp_goals: int | None
    home_pp_opportunities: int | None
    away_goalies: tuple[NHLGoalieBoxscore, ...]
    home_goalies: tuple[NHLGoalieBoxscore, ...]
    source_uri: str
    source_raw_sha256: str
    source_version: str

    def __post_init__(self) -> None:
        if not self.game_id or not self.season or not self.source_version:
            raise ValueError("game identity/source_version required")
        start = _utc(self.start_time_utc, "start_time_utc")
        captured = _utc(self.captured_at, "captured_at")
        if captured <= start:
            raise ValueError("completed-game boxscore must be retrieved after puck drop")
        if self.game_state.upper() not in _FINAL_STATES:
            raise ValueError("boxscore must be final/off before use as completed history")
        if not self.away_team_id or not self.home_team_id or self.away_team_id == self.home_team_id:
            raise ValueError("distinct official home/away team ids required")
        if not self.away_abbrev or not self.home_abbrev:
            raise ValueError("team abbreviations required")
        counts = (
            self.away_regulation_goals, self.home_regulation_goals,
            self.away_final_goals, self.home_final_goals,
            self.away_sog, self.home_sog,
        )
        if min(counts) < 0:
            raise ValueError("goals/SOG must be nonnegative")
        if self.away_regulation_goals > self.away_final_goals or self.home_regulation_goals > self.home_final_goals:
            raise ValueError("regulation goals cannot exceed final goals")
        for goals, opportunities in (
            (self.away_pp_goals, self.away_pp_opportunities),
            (self.home_pp_goals, self.home_pp_opportunities),
        ):
            if (goals is None) != (opportunities is None):
                raise ValueError("power-play goals/opportunities must be present together")
            if goals is not None and opportunities is not None:
                if goals < 0 or opportunities < 0 or goals > opportunities:
                    raise ValueError("invalid power-play counts")
        expected_uri = BOXSCORE_ENDPOINT.format(game_id=self.game_id)
        if self.source_uri != expected_uri:
            raise ValueError("official NHL Gamecenter boxscore URI required")
        if not _SHA256.fullmatch(self.source_raw_sha256.lower()):
            raise ValueError("valid raw boxscore SHA-256 required")

    def as_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["away_goalies"] = [asdict(g) for g in self.away_goalies]
        payload["home_goalies"] = [asdict(g) for g in self.home_goalies]
        return payload


def _team_identity(payload: Mapping[str, Any], side: str) -> tuple[str, str, int, int, tuple[int, int] | None]:
    team = payload.get(f"{side}Team")
    if not isinstance(team, Mapping):
        raise ValueError(f"official boxscore missing {side}Team")
    team_id = str(team.get("id") or "").strip()
    abbrev = str(team.get("abbrev") or "").strip().upper()
    if not team_id or not abbrev:
        raise ValueError(f"official boxscore missing {side} team identity")
    score = _nonnegative_int(team.get("score"), f"{side} score")
    sog = _nonnegative_int(team.get("sog"), f"{side} sog")
    pp = _power_play(team.get("powerPlayConversion"))
    return team_id, abbrev, score, sog, pp


def _regulation_goals(boxscore: Mapping[str, Any], side: str) -> int:
    linescore = boxscore.get("linescore")
    if not isinstance(linescore, Mapping):
        raise ValueError("official boxscore missing linescore")
    periods = linescore.get("byPeriod")
    if not isinstance(periods, Sequence) or isinstance(periods, (str, bytes, bytearray)):
        raise ValueError("official boxscore missing linescore.byPeriod")
    total = 0
    seen: set[int] = set()
    for row in periods:
        if not isinstance(row, Mapping):
            raise ValueError("linescore period row must be a mapping")
        desc = row.get("periodDescriptor") or {}
        if not isinstance(desc, Mapping):
            raise ValueError("linescore periodDescriptor must be a mapping")
        number = int(row.get("period") or desc.get("number") or 0)
        if 1 <= number <= 3:
            total += _nonnegative_int(row.get(side), f"period {number} {side} goals")
            seen.add(number)
    if seen != {1, 2, 3}:
        raise ValueError("complete regulation periods 1-3 required")
    return total


def _goalies(boxscore: Mapping[str, Any], side: str) -> tuple[NHLGoalieBoxscore, ...]:
    player_stats = boxscore.get("playerByGameStats")
    if not isinstance(player_stats, Mapping):
        return ()
    team = player_stats.get(f"{side}Team")
    if not isinstance(team, Mapping):
        return ()
    rows = team.get("goalies")
    if rows is None:
        return ()
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("goalies must be a list")
    out: list[NHLGoalieBoxscore] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("goalie row must be a mapping")
        player_id = str(row.get("playerId") or "").strip()
        if not player_id:
            raise ValueError("goalie row missing playerId")
        saves_shots = _save_shots_against(row.get("saveShotsAgainst"))
        saves = None if saves_shots is None else saves_shots[0]
        shots = None if saves_shots is None else saves_shots[1]
        out.append(NHLGoalieBoxscore(
            player_id=player_id,
            goals_against=_nonnegative_int(row.get("goalsAgainst", 0), "goalie goalsAgainst"),
            saves=saves,
            shots_against=shots,
            toi_seconds=_toi_seconds(row.get("toi")),
        ))
    return tuple(sorted(out, key=lambda g: g.player_id))


def build_official_completed_game(
    *,
    payload: Mapping[str, Any],
    captured_at: str,
    raw_sha256: str,
    source_uri: str | None = None,
    source_version: str = "nhl-web-api-v1",
) -> NHLOfficialCompletedGame:
    """Normalize an already-fetched official final Gamecenter boxscore.

    No HTTP request is performed here.  The caller supplies the real retrieval
    timestamp and SHA-256 of the exact raw response bytes.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("official boxscore payload must be a mapping")
    game_id = str(payload.get("id") or "").strip()
    if not game_id:
        raise ValueError("official boxscore game id required")
    uri = source_uri or BOXSCORE_ENDPOINT.format(game_id=game_id)
    if uri != BOXSCORE_ENDPOINT.format(game_id=game_id):
        raise ValueError("official NHL Gamecenter boxscore URI required")
    game_state = str(payload.get("gameState") or "").strip().upper()
    if game_state not in _FINAL_STATES:
        raise ValueError("official boxscore is not final/off")
    start_time = str(payload.get("startTimeUTC") or "").strip()
    if not start_time:
        raise ValueError("official boxscore startTimeUTC required")
    season = str(payload.get("season") or "").strip()
    game_date = str(payload.get("gameDate") or "").strip()
    if not season or not game_date:
        raise ValueError("official boxscore season/gameDate required")
    game_type = _nonnegative_int(payload.get("gameType"), "gameType")

    away_id, away_abbrev, away_final, away_sog, away_pp = _team_identity(payload, "away")
    home_id, home_abbrev, home_final, home_sog, home_pp = _team_identity(payload, "home")
    boxscore = payload.get("boxscore")
    if not isinstance(boxscore, Mapping):
        raise ValueError("official boxscore object required")

    return NHLOfficialCompletedGame(
        game_id=game_id,
        season=season,
        game_type=game_type,
        game_date=game_date,
        start_time_utc=start_time,
        captured_at=_utc(captured_at, "captured_at").isoformat(),
        game_state=game_state,
        away_team_id=away_id,
        home_team_id=home_id,
        away_abbrev=away_abbrev,
        home_abbrev=home_abbrev,
        away_regulation_goals=_regulation_goals(boxscore, "away"),
        home_regulation_goals=_regulation_goals(boxscore, "home"),
        away_final_goals=away_final,
        home_final_goals=home_final,
        away_sog=away_sog,
        home_sog=home_sog,
        away_pp_goals=None if away_pp is None else away_pp[0],
        away_pp_opportunities=None if away_pp is None else away_pp[1],
        home_pp_goals=None if home_pp is None else home_pp[0],
        home_pp_opportunities=None if home_pp is None else home_pp[1],
        away_goalies=_goalies(boxscore, "away"),
        home_goalies=_goalies(boxscore, "home"),
        source_uri=uri,
        source_raw_sha256=str(raw_sha256).lower(),
        source_version=str(source_version),
    )


def raw_sha256(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("raw response must be bytes")
    return sha256(bytes(raw)).hexdigest()


def completed_game_from_json_dict(payload: Mapping[str, Any]) -> NHLOfficialCompletedGame:
    """Restore a previously normalized receipt without changing provenance."""
    data = dict(payload)
    data["away_goalies"] = tuple(NHLGoalieBoxscore(**g) for g in data.get("away_goalies", ()))
    data["home_goalies"] = tuple(NHLGoalieBoxscore(**g) for g in data.get("home_goalies", ()))
    return NHLOfficialCompletedGame(**data)


def dataset_sha256(games: Sequence[NHLOfficialCompletedGame]) -> str:
    ordered = [g.as_json_dict() for g in sorted(games, key=lambda x: (_utc(x.start_time_utc, "start_time_utc"), x.game_id))]
    raw = json.dumps(ordered, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


__all__ = [
    "NHL_WEB_API_BASE", "BOXSCORE_ENDPOINT", "SOURCE_REFERENCES",
    "NHLGoalieBoxscore", "NHLOfficialCompletedGame",
    "build_official_completed_game", "completed_game_from_json_dict",
    "raw_sha256", "dataset_sha256",
]
