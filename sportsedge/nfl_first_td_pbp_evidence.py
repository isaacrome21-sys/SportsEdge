"""NFL first-touchdown postgame attribution evidence packet, NOT a model.

This module only identifies the first *credited scorer* from a complete
ordered postgame play-by-play packet. It never infers scorer from QB pass
yards, final score, final team TD count, a play's passer, or the side
with most touchdowns. First touchdown includes receiving, rushing,
defensive, recovery and return TD; recipient/player attribution comes
from the original official-scoring event, not a statistical proxy.

Provider "complete" and source SHA strings are operator assertions, not
independent evidence certification. Every output is UNVERIFIED, not
historically model-admitted, and cannot become a wagering estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence
import re

VERSION = "NFL_FIRST_TD_PBP_ATTRIBUTION_V1"
TOUCHDOWN_TYPES = frozenset({
    "RUSHING", "RECEIVING", "INTERCEPTION_RETURN", "FUMBLE_RETURN",
    "KICKOFF_RETURN", "PUNT_RETURN", "BLOCKED_KICK_RETURN",
    "OTHER_EXPLICIT_CREDIT",
})
HEX_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")


class FirstTDEvidenceError(ValueError):
    """Named fail-closed evidence refusal."""


@dataclass(frozen=True)
class FirstTDCandidate:
    game_id: str
    status: str
    touchdown_found: bool
    credited_player_id: str | None
    scoring_team_id: str | None
    touchdown_type: str | None
    first_touchdown_play_index: int | None
    source_event_id: str | None
    evidence_sha256: str
    version: str = VERSION
    complete_official_attribution_verified: bool = False
    eligible: bool = False
    research_only: bool = True
    model_p_authority: bool = False
    play_authority: bool = False
    staking_authority: bool = False
    market_test: str = "NO_MARKET_TEST"


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise FirstTDEvidenceError(f"{field}_ID_REQUIRED")
    return value


def _time(value: Any, field: str):
    if not isinstance(value, str) or not value:
        raise FirstTDEvidenceError(f"{field}_TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FirstTDEvidenceError(f"{field}_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise FirstTDEvidenceError(f"{field}_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha(value: Any, field: str):
    if not isinstance(value, str) or not HEX_SHA.fullmatch(value):
        raise FirstTDEvidenceError(f"{field}_SHA256_REQUIRED")
    return value.lower()


def first_td_from_complete_pbp(packet: Mapping[str, Any]) -> FirstTDCandidate:
    """A settlement-evidence CANDIDATE, not official settlement authority.

    Required packet fields: game_id, scheduled_start_utc,
    completed_at_utc, observed_at_utc, source_snapshot_sha256,
    away_team_id, home_team_id, final_status='FINAL',
    complete_play_by_play=True, expected_play_count (>=1), plays.

    Every play must include a source_event_id, play_index 1..N
    (contiguous packet sequence, not original provider ID), period,
    is_touchdown boolean, source_game_id. Scoring plays must include
    credited_player_id, credited_team_id and touchdown_type.
    """
    if not isinstance(packet, Mapping):
        raise FirstTDEvidenceError("PBP_PACKET_REQUIRED")
    game_id = _id(packet.get("game_id"), "GAME")
    away_id = _id(packet.get("away_team_id"), "AWAY_TEAM")
    home_id = _id(packet.get("home_team_id"), "HOME_TEAM")
    if away_id == home_id:
        raise FirstTDEvidenceError("TEAM_IDENTITY_COLLISION")
    start = _time(packet.get("scheduled_start_utc"), "START")
    finished = _time(packet.get("completed_at_utc"), "COMPLETED")
    observed = _time(packet.get("observed_at_utc"), "OBSERVED")
    if not start < finished <= observed:
        raise FirstTDEvidenceError("POSTGAME_OBSERVATION_TIME_INVALID")
    if packet.get("final_status") != "FINAL" or (
            packet.get("complete_play_by_play") is not True):
        raise FirstTDEvidenceError("OFFICIAL_FULL_GAME_PBP_UNCONFIRMED")
    source_sha = _sha(packet.get("source_snapshot_sha256"),
                     "SOURCE_SNAPSHOT")
    plays = packet.get("plays")
    expected = packet.get("expected_play_count")
    if (not isinstance(plays, Sequence) or isinstance(plays, (str, bytes))
            or type(expected) is not int or expected < 1 or len(plays) != expected):
        raise FirstTDEvidenceError("FULL_PLAY_SEQUENCE_COUNT_REQUIRED")
    source_ids = set()
    previous_period = 0
    first = None
    immutable_rows = []
    for index, event in enumerate(plays, 1):
        if not isinstance(event, Mapping) or event.get("source_game_id") != game_id:
            raise FirstTDEvidenceError("CROSS_GAME_OR_NONOBJECT_PLAY")
        if type(event.get("play_index")) is not int or (
                event["play_index"] != index):
            raise FirstTDEvidenceError("NONCONTIGUOUS_OR_REORDERED_PLAY")
        eid = _id(event.get("source_event_id"), "SOURCE_EVENT")
        if eid in source_ids:
            raise FirstTDEvidenceError("DUPLICATE_SOURCE_EVENT")
        source_ids.add(eid)
        period = event.get("period")
        if type(period) is not int or not 1 <= period <= 9 or (
                period < previous_period):
            raise FirstTDEvidenceError("PERIOD_ORDER_INVALID")
        previous_period = period
        td = event.get("is_touchdown")
        if type(td) is not bool:
            raise FirstTDEvidenceError("TOUCHDOWN_FLAG_REQUIRED")
        counted = {
            "source_event_id": eid, "play_index": index, "period": period,
            "is_touchdown": td,
        }
        if td:
            # Never guess the scorer for a throw: the receiver, not the
            # passer, is officially credited on a receiving touchdown.
            pid = _id(event.get("credited_player_id"), "CREDITED_PLAYER")
            team = _id(event.get("credited_team_id"), "CREDITED_TEAM")
            if team not in {away_id, home_id}:
                raise FirstTDEvidenceError("CREDITED_TEAM_NOT_IN_FIXTURE")
            kind = event.get("touchdown_type")
            if kind not in TOUCHDOWN_TYPES:
                raise FirstTDEvidenceError("TOUCHDOWN_TYPE_UNVERIFIED")
            counted.update({
                "credited_player_id": pid, "credited_team_id": team,
                "touchdown_type": kind,
            })
            if first is None:
                first = counted
        immutable_rows.append(counted)
    digest = hashlib.sha256(json.dumps({
        "version": VERSION, "game_id": game_id,
        "source_snapshot_sha256": source_sha,
        "completed_at_utc": finished.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "expected_play_count": expected, "plays": immutable_rows,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return FirstTDCandidate(
        game_id=game_id,
        status="POSTGAME_ATTRIBUTION_CANDIDATE_UNVERIFIED",
        touchdown_found=first is not None,
        credited_player_id=first["credited_player_id"] if first else None,
        scoring_team_id=first["credited_team_id"] if first else None,
        touchdown_type=first["touchdown_type"] if first else None,
        first_touchdown_play_index=first["play_index"] if first else None,
        source_event_id=first["source_event_id"] if first else None,
        evidence_sha256=digest,
    )
