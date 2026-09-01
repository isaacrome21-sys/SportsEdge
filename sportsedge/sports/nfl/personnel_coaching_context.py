from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .context_autopull import NFLContextError


@dataclass(frozen=True)
class PersonnelSnapshot:
    team_id: str
    eleven_personnel_rate: float | None
    twelve_personnel_rate: float | None
    thirteen_personnel_rate: float | None
    empty_rate: float | None
    nickel_rate: float | None
    dime_rate: float | None
    ol_continuity_starts: int | None
    projected_ol_starters_known: bool
    starting_secondary_known: bool


@dataclass(frozen=True)
class CoachingSnapshot:
    team_id: str
    neutral_pass_rate: float | None
    early_down_pass_rate: float | None
    pace_seconds_per_play: float | None
    no_huddle_rate: float | None
    fourth_down_go_rate: float | None
    two_minute_pass_rate: float | None
    red_zone_pass_rate: float | None
    overall_pass_rate: float | None
    overall_rush_rate: float | None
    offensive_plays_per_game_proxy: float | None
    pass_attempts_per_game: float | None
    carries_per_game: float | None
    sacks_suffered_per_game: float | None
    penalties_per_play_proxy: float | None
    sample_games: int | None


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _rate(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if not 0.0 <= x <= 1.0:
        raise NFLContextError(f"{field} outside [0,1]")
    return x


def _optional_float(value: Any, field: str, *, positive: bool = False) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if positive and x < 0:
        raise NFLContextError(f"{field} invalid")
    return x


def build_personnel_snapshot(row: Mapping[str, Any]) -> PersonnelSnapshot:
    starts = row.get("ol_continuity_starts")
    return PersonnelSnapshot(
        team_id=str(row.get("team_id") or "").upper(),
        eleven_personnel_rate=_rate(row.get("eleven_personnel_rate"), "eleven_personnel_rate"),
        twelve_personnel_rate=_rate(row.get("twelve_personnel_rate"), "twelve_personnel_rate"),
        thirteen_personnel_rate=_rate(row.get("thirteen_personnel_rate"), "thirteen_personnel_rate"),
        empty_rate=_rate(row.get("empty_rate"), "empty_rate"),
        nickel_rate=_rate(row.get("nickel_rate"), "nickel_rate"),
        dime_rate=_rate(row.get("dime_rate"), "dime_rate"),
        ol_continuity_starts=None if starts in (None, "") else int(starts),
        projected_ol_starters_known=bool(row.get("projected_ol_starters_known", False)),
        starting_secondary_known=bool(row.get("starting_secondary_known", False)),
    )


def build_coaching_snapshot(row: Mapping[str, Any]) -> CoachingSnapshot:
    pace = row.get("pace_seconds_per_play")
    if pace not in (None, "") and float(pace) <= 0:
        raise NFLContextError("pace_seconds_per_play invalid")
    sample_games = row.get("sample_games")
    if sample_games not in (None, "") and int(sample_games) < 0:
        raise NFLContextError("sample_games invalid")
    return CoachingSnapshot(
        team_id=str(row.get("team_id") or "").upper(),
        neutral_pass_rate=_rate(row.get("neutral_pass_rate"), "neutral_pass_rate"),
        early_down_pass_rate=_rate(row.get("early_down_pass_rate"), "early_down_pass_rate"),
        pace_seconds_per_play=None if pace in (None, "") else float(pace),
        no_huddle_rate=_rate(row.get("no_huddle_rate"), "no_huddle_rate"),
        fourth_down_go_rate=_rate(row.get("fourth_down_go_rate"), "fourth_down_go_rate"),
        two_minute_pass_rate=_rate(row.get("two_minute_pass_rate"), "two_minute_pass_rate"),
        red_zone_pass_rate=_rate(row.get("red_zone_pass_rate"), "red_zone_pass_rate"),
        overall_pass_rate=_rate(row.get("overall_pass_rate"), "overall_pass_rate"),
        overall_rush_rate=_rate(row.get("overall_rush_rate"), "overall_rush_rate"),
        offensive_plays_per_game_proxy=_optional_float(row.get("offensive_plays_per_game_proxy"), "offensive_plays_per_game_proxy", positive=True),
        pass_attempts_per_game=_optional_float(row.get("pass_attempts_per_game"), "pass_attempts_per_game", positive=True),
        carries_per_game=_optional_float(row.get("carries_per_game"), "carries_per_game", positive=True),
        sacks_suffered_per_game=_optional_float(row.get("sacks_suffered_per_game"), "sacks_suffered_per_game", positive=True),
        penalties_per_play_proxy=_rate(row.get("penalties_per_play_proxy"), "penalties_per_play_proxy"),
        sample_games=None if sample_games in (None, "") else int(sample_games),
    )


def build_personnel_provider(*, game_id: str, as_of: Any, source_uri: str, source_sha256: str, rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not str(source_uri).startswith("https://"):
        raise NFLContextError("personnel source_uri must be https")
    pit = _utc(as_of, "as_of")
    payload = {"game_id": str(game_id), "teams": [asdict(build_personnel_snapshot(r)) for r in rows]}
    return {"status": "AVAILABLE" if rows else "MISSING", "payload": payload, "source_name": "OFFICIAL_DEPTH_CHARTS+PIT_GAME_LOGS", "source_uri": source_uri, "source_sha256": source_sha256, "observed_at": pit}


def build_coaching_provider(*, game_id: str, as_of: Any, source_uri: str, source_sha256: str, rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    if not str(source_uri).startswith("https://"):
        raise NFLContextError("coaching source_uri must be https")
    pit = _utc(as_of, "as_of")
    payload = {"game_id": str(game_id), "teams": [asdict(build_coaching_snapshot(r)) for r in rows]}
    return {"status": "AVAILABLE" if rows else "MISSING", "payload": payload, "source_name": "PIT_PLAY_BY_PLAY_COACHING_HISTORY", "source_uri": source_uri, "source_sha256": source_sha256, "observed_at": pit}
