"""Fail-closed CFB depth-chart snapshot contract for prop live inputs.

This module validates point-in-time source snapshots only. It does not fetch web
pages, create Model_P, or promote any market.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping


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


def content_sha256(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def validate_depth_snapshot(
    snapshot: Mapping[str, Any],
    *,
    previous_game_end: str,
    expected_content_sha256: str | None = None,
) -> dict[str, Any]:
    required = (
        "source_id",
        "source_kind",
        "retrieved_at",
        "source_updated_at",
        "source_url",
        "content_sha256",
        "team_id",
        "players",
    )
    out = dict(snapshot)
    for key in required:
        if key not in out:
            raise CFBDepthSourceError(f"CFB_DEPTH_SNAPSHOT_FIELD_REQUIRED:{key}")

    if out["source_id"] != "TWO_DEEP_PROJECTED_TWO_DEEP":
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_ID_INVALID")
    if out["source_kind"] != "PROJECTED_TWO_DEEP":
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_KIND_INVALID")
    if not str(out["source_url"]).startswith("https://www.thetwodeep.com/college/"):
        raise CFBDepthSourceError("CFB_DEPTH_SOURCE_URL_INVALID")

    retrieved = _dt(out["retrieved_at"], "CFB_DEPTH_RETRIEVED_AT_INVALID")
    updated = _dt(out["source_updated_at"], "CFB_DEPTH_SOURCE_UPDATED_AT_INVALID")
    previous = _dt(previous_game_end, "CFB_DEPTH_PREVIOUS_GAME_END_INVALID")
    if retrieved < updated:
        raise CFBDepthSourceError("CFB_DEPTH_RETRIEVED_BEFORE_SOURCE_UPDATE")
    if updated <= previous:
        raise CFBDepthSourceError("DEPTH_CHART_STALE")

    digest = _hex64(out["content_sha256"], "CFB_DEPTH_CONTENT_SHA256_INVALID")
    if expected_content_sha256 is not None:
        expected = _hex64(expected_content_sha256, "CFB_DEPTH_EXPECTED_SHA256_INVALID")
        if digest != expected:
            raise CFBDepthSourceError("CFB_DEPTH_CONTENT_SHA256_MISMATCH")

    players = out["players"]
    if not isinstance(players, list) or not players:
        raise CFBDepthSourceError("CFB_DEPTH_PLAYERS_REQUIRED")
    seen: set[str] = set()
    for row in players:
        if not isinstance(row, Mapping):
            raise CFBDepthSourceError("CFB_DEPTH_PLAYER_INVALID")
        player_id = str(row.get("player_id") or "").strip()
        if not player_id or player_id in seen:
            raise CFBDepthSourceError("CFB_DEPTH_PLAYER_ID_INVALID")
        seen.add(player_id)
        if not str(row.get("position") or "").strip():
            raise CFBDepthSourceError("CFB_DEPTH_PLAYER_POSITION_REQUIRED")
        depth_rank = row.get("depth_rank")
        if not isinstance(depth_rank, int) or isinstance(depth_rank, bool) or depth_rank < 1:
            raise CFBDepthSourceError("CFB_DEPTH_RANK_INVALID")
        if not isinstance(row.get("unavailable"), bool):
            raise CFBDepthSourceError("CFB_DEPTH_UNAVAILABLE_FLAG_REQUIRED")

    out["retrieved_at"] = retrieved.isoformat()
    out["source_updated_at"] = updated.isoformat()
    out["content_sha256"] = digest
    out["promotion_authority"] = False
    out["model_p_authority"] = False
    return out


def require_player_depth_usable(
    *,
    primary_player: Mapping[str, Any],
    corroborating_starter_player_id: str,
) -> None:
    if primary_player.get("unavailable") is True:
        raise CFBDepthSourceError("PLAYER_UNAVAILABLE")
    if int(primary_player.get("depth_rank", 0)) == 1:
        primary_id = str(primary_player.get("player_id") or "").strip()
        other_id = str(corroborating_starter_player_id or "").strip()
        if not other_id or primary_id != other_id:
            raise CFBDepthSourceError("STARTER_CONFLICT")
