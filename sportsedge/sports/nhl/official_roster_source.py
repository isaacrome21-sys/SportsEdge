from __future__ import annotations

"""Fail-closed official NHL roster identity receipts.

This source boundary verifies only roster/player identity. A goalie appearing on
an official roster is NOT evidence that the goalie is the confirmed starter, so
this module never upgrades PROJECTED to CONFIRMED. It binds the exact normalized
official payload to a SHA-256 receipt captured strictly before puck drop.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .features import GoalieState

NHL_WEB_API_BASE = "https://api-web.nhle.com"
ROSTER_ENDPOINT = NHL_WEB_API_BASE + "/v1/roster/{team}/current"
SCHEMA_REFERENCES = (
    "pseudo-r/Public-NHL-API:docs/web-api/teams.md",
    "Zmalski/NHL-API-Reference:README.md",
)


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _localized_name(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("default", "en", "fr"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _player(row: Mapping[str, Any], *, group: str) -> dict[str, Any]:
    pid = str(row.get("id") or row.get("playerId") or "").strip()
    if not pid:
        raise ValueError(f"{group} row missing player id")
    first = _localized_name(row.get("firstName"))
    last = _localized_name(row.get("lastName"))
    position = str(row.get("positionCode") or row.get("position") or "").strip().upper()
    if not position:
        position = "G" if group == "goalies" else "UNKNOWN"
    return {
        "player_id": pid,
        "name": " ".join(part for part in (first, last) if part).strip() or pid,
        "position": position,
        "group": group,
    }


def build_official_roster_receipt(
    *,
    team: str,
    puck_drop: Any,
    captured_at: Any,
    payload: Mapping[str, Any],
    source_uri: str | None = None,
    source_version: str = "nhl-web-api-v1",
) -> Mapping[str, Any]:
    """Normalize an already-fetched official NHL roster payload.

    The caller is responsible for preserving the exact raw HTTP bytes/headers if
    they are needed for stronger evidence. The deterministic digest here binds
    the normalized JSON object supplied to this function.
    """
    code = str(team).strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("team must be a three-letter NHL code")
    puck = _utc(puck_drop, "puck_drop")
    captured = _utc(captured_at, "captured_at")
    if captured >= puck:
        raise ValueError("PIT violation: roster receipt must predate puck drop")
    uri = source_uri or ROSTER_ENDPOINT.format(team=code)
    expected_uri = ROSTER_ENDPOINT.format(team=code)
    if uri != expected_uri:
        raise ValueError("official roster source URI mismatch")
    if not source_version.strip():
        raise ValueError("source_version required")
    if not isinstance(payload, Mapping):
        raise ValueError("roster payload must be a mapping")

    players: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in ("forwards", "defensemen", "goalies"):
        rows = payload.get(group)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            raise ValueError(f"official roster payload missing {group} list")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError(f"{group} row must be a mapping")
            p = _player(row, group=group)
            if p["player_id"] in seen:
                raise ValueError(f"duplicate roster player id:{p['player_id']}")
            seen.add(p["player_id"])
            players.append(p)

    if not players:
        raise ValueError("official roster payload is empty")
    goalie_ids = tuple(sorted(p["player_id"] for p in players if p["group"] == "goalies"))
    if not goalie_ids:
        raise ValueError("official roster contains no goalies")

    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return {
        "status": "AVAILABLE",
        "team": code,
        "puck_drop": puck,
        "captured_at": captured,
        "source_uri": uri,
        "source_version": source_version,
        "normalized_sha256": sha256(normalized).hexdigest(),
        "players": tuple(sorted(players, key=lambda p: (p["group"], p["player_id"]))),
        "goalie_ids": goalie_ids,
        "starting_goalie_confirmed": False,
        "authority": "IDENTITY_ONLY / NOT STARTER CONFIRMATION / NOT Model_P / NOT OFFICIAL",
    }


def verify_goalie_roster_identity(goalie: GoalieState, receipt: Mapping[str, Any]) -> GoalieState:
    """Require a model goalie identity to exist in the official pregame roster.

    This intentionally preserves the caller's PROJECTED/CONFIRMED status rather
    than manufacturing starter confirmation from roster membership.
    """
    goalie.validate()
    if receipt.get("status") != "AVAILABLE":
        raise ValueError("official roster receipt unavailable")
    ids = {str(x) for x in receipt.get("goalie_ids", ())}
    if goalie.goalie_id not in ids:
        raise ValueError(f"goalie not present on official roster:{goalie.goalie_id}")
    return goalie


__all__ = [
    "NHL_WEB_API_BASE", "ROSTER_ENDPOINT", "SCHEMA_REFERENCES",
    "build_official_roster_receipt", "verify_goalie_roster_identity",
]
