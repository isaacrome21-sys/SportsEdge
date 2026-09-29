from __future__ import annotations

"""Stage official NHL Gamecenter play-by-play without inventing timestamps.

The official ``api-web.nhle.com`` gamecenter feed exposes event order, period
clock, coordinates, participants, shot type and ``situationCode``. It does not
provide an absolute UTC timestamp for each event in the ordinary PBP payload.
This adapter therefore stages deterministic shot context first and materializes
``NHLShotEvent`` only when the caller supplies an independently proven absolute
UTC time for every staged shot.

Rebound/rush rules are frozen, auditable sequence rules inspired by public NHL
feature pipelines, not learned labels. Research/history plumbing only; no
Model_P, Truth Gate, promotion, staking, or OFFICIAL authority is created.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Sequence

from .ingestion import NHLShotEvent

OFFICIAL_PBP_PREFIX = "https://api-web.nhle.com/v1/gamecenter/"
SHOT_TYPES = frozenset({"shot-on-goal", "goal", "missed-shot"})
REBOUND_MAX_SECONDS = 3
RUSH_MAX_SECONDS = 4
BLUE_LINE_X = 25.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class NHLStagedShot:
    game_id: str
    event_id: str
    sort_order: int
    period: int
    time_in_period: str
    team_id: str
    shooter_id: str
    goalie_id: str | None
    x: float
    y: float
    shot_type: str
    strength_state: str
    is_goal: bool
    is_rebound: bool
    is_rush: bool
    source_uri: str
    source_raw_sha256: str
    source_version: str


def _clock_seconds(value: Any) -> int:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid timeInPeriod:{text}")
    try:
        minute, second = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"invalid timeInPeriod:{text}") from exc
    if minute < 0 or second < 0 or second >= 60:
        raise ValueError(f"invalid timeInPeriod:{text}")
    return minute * 60 + second


def decode_situation_code(situation_code: Any, *, shooter_is_home: bool) -> str:
    """Decode official 4-digit situationCode into EV/PP/SH/EN.

    Format: away-goalie, away-skaters, home-skaters, home-goalie. If the
    defending goalie is pulled, empty-net context takes precedence.
    """
    code = str(situation_code or "")
    if len(code) != 4 or not code.isdigit():
        raise ValueError(f"malformed situationCode:{code!r}")
    away_goalie, away_skaters, home_skaters, home_goalie = code
    if shooter_is_home:
        shooter_skaters, defender_skaters, defending_goalie = home_skaters, away_skaters, away_goalie
    else:
        shooter_skaters, defender_skaters, defending_goalie = away_skaters, home_skaters, home_goalie
    if defending_goalie == "0":
        return "EN"
    if int(shooter_skaters) > int(defender_skaters):
        return "PP"
    if int(shooter_skaters) < int(defender_skaters):
        return "SH"
    return "EV"


def _shot_identity(play: Mapping[str, Any]) -> tuple[str, str | None]:
    details = play.get("details") or {}
    if not isinstance(details, Mapping):
        raise ValueError("play details must be a mapping")
    kind = str(play.get("typeDescKey") or "")
    if kind == "goal":
        shooter = details.get("scoringPlayerId")
    else:
        shooter = details.get("shootingPlayerId")
    if shooter in (None, ""):
        raise ValueError("shot missing shooter identity")
    goalie = details.get("goalieInNetId")
    return str(shooter), None if goalie in (None, "") else str(goalie)


def _xy(play: Mapping[str, Any]) -> tuple[float, float]:
    details = play.get("details") or {}
    try:
        x, y = float(details["xCoord"]), float(details["yCoord"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("shot missing finite coordinates") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("shot missing finite coordinates")
    return x, y


def _home_defending_side(play: Mapping[str, Any]) -> str:
    value = str(play.get("homeTeamDefendingSide") or "").strip().lower()
    if value not in {"left", "right"}:
        raise ValueError("homeTeamDefendingSide required for rush context")
    return value


def _attack_sign(*, shooter_is_home: bool, home_defending_side: str) -> float:
    # If home defends left, home attacks right (+x); if home defends right,
    # home attacks left (-x). Away is the opposite.
    home_sign = 1.0 if home_defending_side == "left" else -1.0
    return home_sign if shooter_is_home else -home_sign


def _source_binding(source_uri: str, raw_sha256: str, game_id: str) -> None:
    expected = f"{OFFICIAL_PBP_PREFIX}{game_id}/play-by-play"
    if source_uri != expected:
        raise ValueError("official NHL gamecenter play-by-play URI required")
    if not _SHA256.fullmatch(str(raw_sha256).lower()):
        raise ValueError("valid raw NHL PBP SHA-256 required")


def stage_official_nhl_pbp(
    payload: Mapping[str, Any], *, source_uri: str, raw_sha256: str, source_version: str,
) -> tuple[NHLStagedShot, ...]:
    """Parse official PBP and derive deterministic shot sequence context.

    The entire play stream is retained while deriving context so stoppages,
    faceoffs, period boundaries, and team changes correctly break rebound/rush
    chains. Absolute UTC event time is deliberately not synthesized.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("official NHL PBP payload must be a mapping")
    game_id = str(payload.get("id") or payload.get("gameId") or "").strip()
    if not game_id:
        raise ValueError("official NHL PBP game id required")
    _source_binding(source_uri, raw_sha256, game_id)
    if not str(source_version).strip():
        raise ValueError("source_version required")
    home = payload.get("homeTeam") or {}
    away = payload.get("awayTeam") or {}
    home_id = str(home.get("id") or "") if isinstance(home, Mapping) else ""
    away_id = str(away.get("id") or "") if isinstance(away, Mapping) else ""
    if not home_id or not away_id or home_id == away_id:
        raise ValueError("official home/away team identities required")
    plays = payload.get("plays")
    if not isinstance(plays, Sequence) or isinstance(plays, (str, bytes, bytearray)):
        raise ValueError("official NHL PBP plays required")

    ordered = sorted(plays, key=lambda p: int(p.get("sortOrder", p.get("eventId", 0))))
    out: list[NHLStagedShot] = []
    previous: Mapping[str, Any] | None = None
    previous_elapsed: int | None = None
    previous_period: int | None = None

    for play in ordered:
        if not isinstance(play, Mapping):
            raise ValueError("play must be a mapping")
        desc = play.get("periodDescriptor") or {}
        if not isinstance(desc, Mapping) or desc.get("number") in (None, ""):
            raise ValueError("play periodDescriptor.number required")
        period = int(desc["number"])
        elapsed = _clock_seconds(play.get("timeInPeriod"))
        kind = str(play.get("typeDescKey") or "")

        if kind in SHOT_TYPES:
            details = play.get("details") or {}
            if not isinstance(details, Mapping):
                raise ValueError("shot details must be a mapping")
            team_id = str(details.get("eventOwnerTeamId") or "")
            if team_id not in {home_id, away_id}:
                raise ValueError("shot eventOwnerTeamId must match official teams")
            shooter_is_home = team_id == home_id
            shooter_id, goalie_id = _shot_identity(play)
            x, y = _xy(play)
            side = _home_defending_side(play)
            strength = decode_situation_code(play.get("situationCode"), shooter_is_home=shooter_is_home)

            rebound = False
            rush = False
            if previous is not None and previous_period == period and previous_elapsed is not None:
                gap = elapsed - previous_elapsed
                if gap >= 0:
                    prev_kind = str(previous.get("typeDescKey") or "")
                    prev_details = previous.get("details") or {}
                    prev_team = str(prev_details.get("eventOwnerTeamId") or "") if isinstance(prev_details, Mapping) else ""
                    rebound = gap <= REBOUND_MAX_SECONDS and prev_kind == "shot-on-goal" and prev_team == team_id
                    if gap <= RUSH_MAX_SECONDS and isinstance(prev_details, Mapping):
                        px = prev_details.get("xCoord")
                        if px not in (None, ""):
                            try:
                                previous_adjusted_x = _attack_sign(
                                    shooter_is_home=shooter_is_home, home_defending_side=side
                                ) * float(px)
                                current_adjusted_x = _attack_sign(
                                    shooter_is_home=shooter_is_home, home_defending_side=side
                                ) * x
                                rush = previous_adjusted_x <= BLUE_LINE_X and current_adjusted_x > BLUE_LINE_X
                            except (TypeError, ValueError):
                                rush = False

            shot_type = str(details.get("shotType") or kind)
            event_id = str(play.get("eventId") or play.get("sortOrder") or "")
            if not event_id:
                raise ValueError("shot event identity required")
            out.append(NHLStagedShot(
                game_id=game_id,
                event_id=event_id,
                sort_order=int(play.get("sortOrder", play.get("eventId", 0))),
                period=period,
                time_in_period=str(play.get("timeInPeriod")),
                team_id=team_id,
                shooter_id=shooter_id,
                goalie_id=goalie_id,
                x=x,
                y=y,
                shot_type=shot_type,
                strength_state=strength,
                is_goal=kind == "goal",
                is_rebound=rebound,
                is_rush=rush,
                source_uri=source_uri,
                source_raw_sha256=str(raw_sha256).lower(),
                source_version=str(source_version),
            ))

        previous = play
        previous_elapsed = elapsed
        previous_period = period
    return tuple(out)


def materialize_staged_shots(
    staged: Sequence[NHLStagedShot], *, event_time_utc_by_event_id: Mapping[str, str],
) -> tuple[NHLShotEvent, ...]:
    """Materialize model events only with independently supplied absolute UTCs."""
    if not staged:
        return ()
    ids = {shot.event_id for shot in staged}
    missing = sorted(ids - {str(k) for k in event_time_utc_by_event_id})
    if missing:
        raise ValueError("absolute event UTC missing; downstream NHLShotEvent materialization blocked")
    out = []
    for shot in staged:
        out.append(NHLShotEvent(
            game_id=shot.game_id,
            event_id=shot.event_id,
            event_time_utc=str(event_time_utc_by_event_id[shot.event_id]),
            team_id=shot.team_id,
            shooter_id=shot.shooter_id,
            goalie_id=shot.goalie_id,
            x=shot.x,
            y=shot.y,
            shot_type=shot.shot_type,
            strength_state=shot.strength_state,
            is_goal=shot.is_goal,
            is_rebound=shot.is_rebound,
            is_rush=shot.is_rush,
            source=shot.source_uri,
            source_version=f"{shot.source_version}:raw={shot.source_raw_sha256}",
        ))
    return tuple(out)


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


__all__ = [
    "NHLStagedShot", "stage_official_nhl_pbp", "materialize_staged_shots",
    "decode_situation_code", "canonical_payload_sha256",
]
