"""Fail-closed CFB depth-chart snapshot contract for prop live inputs.

This module validates point-in-time source snapshots only. It does not fetch web
pages, create Model_P, or promote any market. The committed JSON policy is the
runtime authority for source identity, freshness/PIT rules, corroboration, and
provenance requirements.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

POLICY_PATH = Path(__file__).resolve().parents[3] / "config/cfb_prop_depth_source_policy_v1.json"
POLICY_SCHEMA_VERSION = "CFB_PROP_DEPTH_SOURCE_POLICY_V1"
_SUPPORTED_FIELDS = frozenset({
    "retrieved_at",
    "source_updated_at",
    "source_url",
    "content_sha256",
    "team_id",
    "players",
})


class CFBDepthSourceError(ValueError):
    pass


def _dt(value: Any, code: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise CFBDepthSourceError(code)
    if len(raw) == 10:
        raw = raw + "T00:00:00+00:00"
    elif raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        out = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CFBDepthSourceError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBDepthSourceError(code)
    return out.astimezone(timezone.utc)


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBDepthSourceError(code)
    return text


def _required_text(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CFBDepthSourceError(code)
    return text


def load_depth_source_policy(path: str | Path = POLICY_PATH) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = p.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_UNREADABLE") from exc
    if not isinstance(payload, Mapping):
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_INVALID")
    out = dict(payload)
    if out.get("schema_version") != POLICY_SCHEMA_VERSION or str(out.get("sport") or "").upper() != "CFB":
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_IDENTITY_INVALID")
    if out.get("status") != "CANDIDATE_INPUT_ONLY":
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_ACTIVATION_REQUIRES_CODE_REVIEW")
    if out.get("promotion_authority") is not False or out.get("model_p_authority") is not False:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_AUTHORITY_INVALID")

    primary = out.get("primary_source")
    if not isinstance(primary, Mapping):
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PRIMARY_INVALID")
    primary_id = _required_text(primary.get("source_id"), "CFB_DEPTH_POLICY_PRIMARY_INVALID")
    primary_kind = _required_text(primary.get("source_kind"), "CFB_DEPTH_POLICY_PRIMARY_INVALID")
    base_url = _required_text(primary.get("base_url"), "CFB_DEPTH_POLICY_PRIMARY_INVALID")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.hostname != "www.thetwodeep.com":
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PRIMARY_URL_INVALID")
    if primary.get("automated_acquisition") is not False or not str(primary.get("automation_blocker") or "").strip():
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PRIMARY_AUTOMATION_INVALID")
    required = primary.get("required_snapshot_fields")
    if not isinstance(required, list) or frozenset(str(x) for x in required) != _SUPPORTED_FIELDS:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_REQUIRED_FIELDS_INVALID")

    corroboration = out.get("corroboration")
    if not isinstance(corroboration, Mapping) or corroboration.get("required_for_prop_dependency") is not True:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_CORROBORATION_INVALID")
    corroboration_id = _required_text(corroboration.get("source_id"), "CFB_DEPTH_POLICY_CORROBORATION_INVALID")
    if corroboration.get("automated_acquisition") is not False or not str(corroboration.get("automation_blocker") or "").strip():
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_CORROBORATION_AUTOMATION_INVALID")
    conflict_blocker = _required_text(corroboration.get("conflict_blocker"), "CFB_DEPTH_POLICY_CORROBORATION_INVALID")

    freshness = out.get("freshness")
    if not isinstance(freshness, Mapping) or freshness.get("rule") != "SOURCE_UPDATED_AFTER_PREVIOUS_GAME":
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_FRESHNESS_INVALID")
    stale_blocker = _required_text(freshness.get("stale_blocker"), "CFB_DEPTH_POLICY_FRESHNESS_INVALID")

    pit = out.get("point_in_time")
    if not isinstance(pit, Mapping) or any(
        pit.get(key) is not True
        for key in (
            "source_update_must_not_follow_retrieval",
            "retrieval_must_not_follow_decision",
            "decision_must_precede_target_game",
            "expected_team_id_required",
            "expected_content_sha256_required",
        )
    ):
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PIT_INVALID")

    availability = out.get("availability")
    if not isinstance(availability, Mapping):
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_AVAILABILITY_INVALID")
    unavailable_blocker = _required_text(availability.get("unavailable_blocker"), "CFB_DEPTH_POLICY_AVAILABILITY_INVALID")

    provenance = out.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PROVENANCE_INVALID")
    if provenance.get("snapshot_hash_algorithm") != "SHA256_BYTES_V1":
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_HASH_ALGORITHM_INVALID")
    if provenance.get("persist_branch") != "data" or provenance.get("append_only") is not True:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PERSISTENCE_INVALID")
    if provenance.get("parser_code_hash_required_before_runtime_wiring") is not True:
        raise CFBDepthSourceError("CFB_DEPTH_POLICY_PARSER_HASH_INVALID")

    out["policy_sha256"] = sha256(raw).hexdigest()
    out["primary_source_id"] = primary_id
    out["primary_source_kind"] = primary_kind
    out["primary_base_url"] = base_url
    out["required_snapshot_fields"] = tuple(required)
    out["corroboration_source_id"] = corroboration_id
    out["conflict_blocker"] = conflict_blocker
    out["stale_blocker"] = stale_blocker
    out["unavailable_blocker"] = unavailable_blocker
    return out


_POLICY = load_depth_source_policy()
POLICY_SHA256 = str(_POLICY["policy_sha256"])
PRIMARY_SOURCE_ID = str(_POLICY["primary_source_id"])
PRIMARY_SOURCE_KIND = str(_POLICY["primary_source_kind"])
PRIMARY_BASE_URL = str(_POLICY["primary_base_url"])
REQUIRED_SNAPSHOT_FIELDS = tuple(_POLICY["required_snapshot_fields"])
CORROBORATION_SOURCE_ID = str(_POLICY["corroboration_source_id"])
CONFLICT_BLOCKER = str(_POLICY["conflict_blocker"])
STALE_BLOCKER = str(_POLICY["stale_blocker"])
UNAVAILABLE_BLOCKER = str(_POLICY["unavailable_blocker"])


def content_sha256(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)):
        raise CFBDepthSourceError("CFB_DEPTH_CONTENT_BYTES_REQUIRED")
    return sha256(bytes(raw)).hexdigest()


def _validate_source_url(value: Any) -> str:
    text = _required_text(value, "CFB_DEPTH_SOURCE_URL_INVALID")
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.hostname != "www.thetwodeep.com" or not parsed.path.startswith("/college/"):
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_URL_INVALID")
    return text


def validate_depth_snapshot(
    snapshot: Mapping[str, Any],
    *,
    previous_game_end: str,
    decision_time: str,
    target_game_start: str,
    expected_team_id: str,
    expected_content_sha256: str,
) -> dict[str, Any]:
    out = dict(snapshot)
    for key in REQUIRED_SNAPSHOT_FIELDS:
        if key not in out:
            raise CFBDepthSourceError(f"CFB_DEPTH_SNAPSHOT_FIELD_REQUIRED:{key}")

    if out.get("source_id") != PRIMARY_SOURCE_ID:
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_ID_INVALID")
    if out.get("source_kind") != PRIMARY_SOURCE_KIND:
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_KIND_INVALID")
    out["source_url"] = _validate_source_url(out.get("source_url"))

    team_id = _required_text(out.get("team_id"), "CFB_DEPTH_TEAM_ID_REQUIRED")
    expected_team = _required_text(expected_team_id, "CFB_DEPTH_EXPECTED_TEAM_ID_REQUIRED")
    if team_id != expected_team:
        raise CFBDepthSourceError("CFB_DEPTH_TEAM_ID_MISMATCH")

    retrieved = _dt(out.get("retrieved_at"), "CFB_DEPTH_RETRIEVED_AT_INVALID")
    updated = _dt(out.get("source_updated_at"), "CFB_DEPTH_SOURCE_UPDATED_AT_INVALID")
    previous = _dt(previous_game_end, "CFB_DEPTH_PREVIOUS_GAME_END_INVALID")
    decision = _dt(decision_time, "CFB_DEPTH_DECISION_TIME_INVALID")
    target = _dt(target_game_start, "CFB_DEPTH_TARGET_GAME_START_INVALID")
    if previous >= target:
        raise CFBDepthSourceError("CFB_DEPTH_GAME_CHRONOLOGY_INVALID")
    if retrieved < updated:
        raise CFBDepthSourceError("CFB_DEPTH_RETRIEVED_BEFORE_SOURCE_UPDATE")
    if updated <= previous:
        raise CFBDepthSourceError(STALE_BLOCKER)
    if retrieved > decision:
        raise CFBDepthSourceError("CFB_DEPTH_RETRIEVED_AFTER_DECISION")
    if decision >= target:
        raise CFBDepthSourceError("CFB_DEPTH_DECISION_NOT_PREGAME")

    digest = _hex64(out.get("content_sha256"), "CFB_DEPTH_CONTENT_SHA256_INVALID")
    expected = _hex64(expected_content_sha256, "CFB_DEPTH_EXPECTED_SHA256_INVALID")
    if digest != expected:
        raise CFBDepthSourceError("CFB_DEPTH_CONTENT_SHA256_MISMATCH")

    players = out.get("players")
    if not isinstance(players, list) or not players:
        raise CFBDepthSourceError("CFB_DEPTH_PLAYERS_REQUIRED")
    seen: set[str] = set()
    normalized_players: list[dict[str, Any]] = []
    for raw_player in players:
        if not isinstance(raw_player, Mapping):
            raise CFBDepthSourceError("CFB_DEPTH_PLAYER_INVALID")
        row = dict(raw_player)
        player_id = _required_text(row.get("player_id"), "CFB_DEPTH_PLAYER_ID_INVALID")
        if player_id in seen:
            raise CFBDepthSourceError("CFB_DEPTH_PLAYER_ID_INVALID")
        seen.add(player_id)
        row["player_id"] = player_id
        row["position"] = _required_text(row.get("position"), "CFB_DEPTH_PLAYER_POSITION_REQUIRED")
        depth_rank = row.get("depth_rank")
        if not isinstance(depth_rank, int) or isinstance(depth_rank, bool) or depth_rank < 1:
            raise CFBDepthSourceError("CFB_DEPTH_RANK_INVALID")
        if not isinstance(row.get("unavailable"), bool):
            raise CFBDepthSourceError("CFB_DEPTH_UNAVAILABLE_FLAG_REQUIRED")
        normalized_players.append(row)

    out["team_id"] = team_id
    out["players"] = normalized_players
    out["retrieved_at"] = retrieved.isoformat()
    out["source_updated_at"] = updated.isoformat()
    out["decision_time"] = decision.isoformat()
    out["target_game_start"] = target.isoformat()
    out["content_sha256"] = digest
    out["policy_sha256"] = POLICY_SHA256
    out["point_in_time_validated"] = True
    out["promotion_authority"] = False
    out["model_p_authority"] = False
    return out


def require_player_depth_usable(
    *,
    primary_player: Mapping[str, Any],
    corroborating_source_id: str,
    corroborating_starter_player_id: str,
) -> None:
    player_id = _required_text(primary_player.get("player_id"), "CFB_DEPTH_PLAYER_ID_INVALID")
    if primary_player.get("unavailable") is True:
        raise CFBDepthSourceError(UNAVAILABLE_BLOCKER)
    if str(corroborating_source_id or "").strip() != CORROBORATION_SOURCE_ID:
        raise CFBDepthSourceError("CFB_DEPTH_CORROBORATION_SOURCE_INVALID")
    rank = primary_player.get("depth_rank")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
        raise CFBDepthSourceError("CFB_DEPTH_RANK_INVALID")
    if rank == 1:
        other_id = _required_text(corroborating_starter_player_id, "CFB_DEPTH_CORROBORATING_STARTER_REQUIRED")
        if player_id != other_id:
            raise CFBDepthSourceError(CONFLICT_BLOCKER)


__all__ = [
    "CFBDepthSourceError",
    "CONFLICT_BLOCKER",
    "CORROBORATION_SOURCE_ID",
    "POLICY_PATH",
    "POLICY_SHA256",
    "PRIMARY_BASE_URL",
    "PRIMARY_SOURCE_ID",
    "PRIMARY_SOURCE_KIND",
    "REQUIRED_SNAPSHOT_FIELDS",
    "STALE_BLOCKER",
    "UNAVAILABLE_BLOCKER",
    "content_sha256",
    "load_depth_source_policy",
    "require_player_depth_usable",
    "validate_depth_snapshot",
]
