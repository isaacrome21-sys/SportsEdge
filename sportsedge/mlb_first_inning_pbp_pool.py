"""MLB first-inning pitcher strikeout / team BTP PIT history foundation.

NOT a pricing engine or proof of PBP source authenticity. This strict
fixture-bound parser consumes normalized, independently verified
*complete* first-inning PA packets to construct exactly prior counts.
No count guessed from linescore run totals or total pitches. Any PBP
identity or completeness gap fails closed; no zero is manufactured for
an absent pitcher. All M21 canonical NO_ENGINE gates remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

VERSION = "MLB_M21_FIRST_INNING_PBP_COMPLETE_PA_POOL_V1"
SUBJECT_KINDS = frozenset({"PITCHER_K", "TEAM_BTP"})
HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")
MIN_PREVIOUS_GAMES = 10


class FirstInningPBPPoolError(ValueError):
    """Named fail-closed source/subject error."""


@dataclass(frozen=True)
class FirstInningPBPPool:
    subject_kind: str
    subject_id: int
    target_game_pk: int
    as_of_utc: str
    historical_game_pks: tuple[int, ...]
    observed_counts: tuple[int, ...]
    evidence_sha256: str
    distribution_status: str = "PIT_HISTORY_ONLY_NO_CALIBRATED_DISTRIBUTION"
    version: str = VERSION
    research_only: bool = True
    eligible: bool = False
    no_engine: bool = True
    market_test: str = "NO_MARKET_TEST"


def _int(value: Any, field: str, *, allow_zero=False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise FirstInningPBPPoolError(f"{field}_INTEGER_REQUIRED")
    return value


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FirstInningPBPPoolError(f"{field}_TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FirstInningPBPPoolError(f"{field}_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise FirstInningPBPPoolError(f"{field}_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise FirstInningPBPPoolError(f"{field}_SOURCE_HASH_REQUIRED")
    return value.lower()


def build_first_inning_pa_pool(
    target: Mapping[str, Any], packets: Sequence[Mapping[str, Any]],
    *, subject_kind: str, subject_id: int, as_of_utc: str,
) -> FirstInningPBPPool:
    """Build source-count history only; **NOT** a probability readout.

    Each packet is a complete historical final game, with two played
    first-inning halves and normalized first-inning PA events. The
    completeness claim and source SHA are still operator-supplied;
    independent StatsAPI/PBP archive attestation is an outside gate.
    """
    if not isinstance(target, Mapping):
        raise FirstInningPBPPoolError("TARGET_IDENTITY_REQUIRED")
    kind = str(subject_kind or "").upper()
    if kind not in SUBJECT_KINDS:
        raise FirstInningPBPPoolError("SUBJECT_MARKET_NOT_RECOGNIZED")
    sid = _int(subject_id, "SUBJECT")
    target_pk = _int(target.get("game_pk"), "TARGET_GAMEPK")
    away_target = _int(target.get("away_team_id"), "TARGET_AWAY_TEAM")
    home_target = _int(target.get("home_team_id"), "TARGET_HOME_TEAM")
    if away_target == home_target:
        raise FirstInningPBPPoolError("TARGET_TEAMS_COLLIDE")
    target_start = _utc(target.get("scheduled_start_utc"), "TARGET_START")
    asof = _utc(as_of_utc, "AS_OF")
    if asof >= target_start:
        raise FirstInningPBPPoolError("AS_OF_NOT_STRICTLY_PREGAME")
    if kind == "TEAM_BTP" and sid not in {away_target, home_target}:
        raise FirstInningPBPPoolError("TEAM_SUBJECT_NOT_IN_TARGET_FIXTURE")
    if (not isinstance(packets, Sequence) or
            isinstance(packets, (str, bytes)) or len(packets) < MIN_PREVIOUS_GAMES):
        raise FirstInningPBPPoolError("INSUFFICIENT_COMPLETE_PRIOR_GAME_PACKETS")
    rows = []
    seen = set()
    for p in packets:
        if not isinstance(p, Mapping):
            raise FirstInningPBPPoolError("INVALID_PBP_PACKET")
        pk = _int(p.get("game_pk"), "PBP_GAMEPK")
        if pk == target_pk or pk in seen:
            raise FirstInningPBPPoolError("PBP_DUPLICATE_OR_TARGET_GAMEPK")
        seen.add(pk)
        away = _int(p.get("away_team_id"), "PBP_AWAY_TEAM")
        home = _int(p.get("home_team_id"), "PBP_HOME_TEAM")
        if away == home:
            raise FirstInningPBPPoolError("PBP_TEAM_IDENTITY_COLLISION")
        home_starter = _int(p.get("home_starter_pitcher_id"), "HOME_STARTER")
        away_starter = _int(p.get("away_starter_pitcher_id"), "AWAY_STARTER")
        if home_starter == away_starter:
            raise FirstInningPBPPoolError("PBP_STARTER_IDENTITY_COLLISION")
        game_start = _utc(p.get("game_start_utc"), "PBP_GAME_START")
        completed = _utc(p.get("completed_at_utc"), "PBP_GAME_COMPLETED")
        observed = _utc(p.get("observed_at_utc"), "PBP_OBSERVED")
        if not game_start < completed <= observed <= asof:
            raise FirstInningPBPPoolError("PBP_NOT_STRICTLY_PRIOR_OR_COMPLETE")
        if p.get("final_status") != "FINAL" or (
                p.get("both_first_inning_halves_complete") is not True):
            raise FirstInningPBPPoolError("FIRST_INNING_PBP_HALVES_INCOMPLETE")
        source_sha = _sha(p.get("source_snapshot_sha256"), "PBP")
        entries = p.get("plate_appearances")
        expected = _int(p.get("expected_first_inning_pa_count"),
                        "EXPECTED_PBP_PA_COUNT", allow_zero=True)
        if (not isinstance(entries, list) or len(entries) != expected or
                expected < 6):
            raise FirstInningPBPPoolError("FIRST_INNING_PA_CENSUS_INCOMPLETE")
        half = {"TOP": [], "BOTTOM": []}
        event_ids = set()
        normalized = []
        for j, play in enumerate(entries, 1):
            if not isinstance(play, Mapping) or (
                    play.get("game_pk") != pk or play.get("inning") != 1):
                raise FirstInningPBPPoolError("CROSS_GAME_OR_NONFIRST_PA")
            if type(play.get("pa_index")) is not int or play["pa_index"] != j:
                raise FirstInningPBPPoolError("PBP_NONCONTIGUOUS_PA_INDEX")
            half_name = play.get("half")
            if half_name not in half:
                raise FirstInningPBPPoolError("PBP_INVALID_HALF")
            if half_name == "TOP" and half["BOTTOM"]:
                raise FirstInningPBPPoolError("PBP_FIRST_INNING_HALF_ORDER")
            event_id = play.get("source_event_id")
            if not isinstance(event_id, str) or not event_id.strip() or (
                    event_id in event_ids):
                raise FirstInningPBPPoolError("MISSING_OR_DUPLICATE_PBP_EVENT")
            event_ids.add(event_id)
            batter = _int(play.get("batter_id"), "PBP_BATTER")
            pitcher = _int(play.get("pitcher_id"), "PBP_PITCHER")
            strikeout = play.get("official_strikeout")
            if type(strikeout) is not bool or play.get("complete_pa") is not True:
                raise FirstInningPBPPoolError("PBP_PA_RESULT_UNVERIFIED")
            if j == 1 and pitcher != home_starter:
                raise FirstInningPBPPoolError("HOME_STARTER_FIRST_PA_MISMATCH")
            if half_name == "BOTTOM" and not half["BOTTOM"] and (
                    pitcher != away_starter):
                raise FirstInningPBPPoolError("AWAY_STARTER_FIRST_PA_MISMATCH")
            half[half_name].append((pitcher, batter, strikeout))
            normalized.append({
                "source_event_id": event_id, "pa_index": j,
                "half": half_name, "pitcher_id": pitcher,
                "batter_id": batter, "official_strikeout": strikeout,
            })
        if min(len(half["TOP"]), len(half["BOTTOM"])) < 3:
            raise FirstInningPBPPoolError("FIRST_INNING_HALF_PA_CENSUS_TOO_SMALL")
        if kind == "TEAM_BTP":
            if sid not in (away, home):
                raise FirstInningPBPPoolError("TEAM_NOT_IN_HISTORICAL_GAME")
            chosen_half = "TOP" if sid == away else "BOTTOM"
            count = len(half[chosen_half])
        else:
            # Subject MUST be documented starting pitcher in exactly one
            # half; reliever appearances do not create a 'prior start'.
            if sid not in (home_starter, away_starter):
                raise FirstInningPBPPoolError("PITCHER_NOT_CONFIRMED_STARTER")
            chosen_half = "TOP" if sid == home_starter else "BOTTOM"
            count = sum(1 for pitcher, _, k in half[chosen_half]
                        if pitcher == sid and k)
        rows.append({
            "game_pk": pk, "count": count,
            "source_snapshot_sha256": source_sha,
            "observed_at_utc": observed.isoformat(),
            "pa_hash": hashlib.sha256(json.dumps(
                normalized, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
        })
    rows.sort(key=lambda x: x["game_pk"])
    evidence = {
        "version": VERSION, "subject_kind": kind, "subject_id": sid,
        "target_game_pk": target_pk, "as_of_utc": asof.isoformat(),
        "prior": rows,
    }
    fingerprint = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FirstInningPBPPool(
        subject_kind=kind, subject_id=sid, target_game_pk=target_pk,
        as_of_utc=asof.isoformat(),
        historical_game_pks=tuple(x["game_pk"] for x in rows),
        observed_counts=tuple(x["count"] for x in rows),
        evidence_sha256=fingerprint)
