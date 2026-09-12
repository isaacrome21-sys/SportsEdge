"""Strict PIT usage-input contract for CFB prop model-candidate inference.

This module does not fetch sportsbook data, infer missing player shares, or grant
promotion authority. It only validates an already captured, market-blind player
participation/usage snapshot and converts it to the live-feature schema consumed
by the frozen shared football prop simulator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from sportsedge.core.simulate.usage import PlayerUsageProfile, TeamUsageProfile

SCHEMA_VERSION = "CFB_PROP_USAGE_INPUT_V1"
LIVE_SCHEMA_VERSION = "CFB_PROP_LIVE_FEATURES_V1"
DEFAULT_MAX_AGE_SECONDS = 2 * 60 * 60
_USAGE_FIELDS = (
    "snap_share", "route_participation", "target_share", "rush_share",
    "red_zone_share",
)
_FORBIDDEN_KEYS = frozenset({
    "price", "prices", "odds", "american_odds", "decimal_odds", "line",
    "market", "markets", "spread", "total", "moneyline", "vig", "no_vig",
    "fair_market_p", "implied_probability", "ticket_pct", "money_pct",
})


class CFBPropUsageInputError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_CANONICAL_INPUT_INVALID") from exc
    return sha256(raw).hexdigest()


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBPropUsageInputError(code)
    return text


def _aware(value: Any, code: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBPropUsageInputError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBPropUsageInputError(code)
    return out.astimezone(timezone.utc)


def _finite_share(value: Any, code: str) -> float:
    if isinstance(value, bool):
        raise CFBPropUsageInputError(code)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBPropUsageInputError(code) from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise CFBPropUsageInputError(code)
    return out


def _reject_market_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in _FORBIDDEN_KEYS or "sportsbook" in name:
                raise CFBPropUsageInputError(
                    f"CFB_PROP_USAGE_MARKET_FIELD_FORBIDDEN:{path}.{key}"
                )
            _reject_market_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_market_fields(child, f"{path}[{idx}]")


def load_usage_input(path: str | Path) -> tuple[dict[str, Any], str]:
    p = Path(path)
    try:
        raw = p.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_INPUT_INVALID") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_SCHEMA_INVALID")
    _reject_market_fields(payload)
    return dict(payload), sha256(raw).hexdigest()


def _team_usage(raw: Any, *, expected_team: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBPropUsageInputError(
            f"CFB_PROP_USAGE_TEAM_BLOCK_REQUIRED:{expected_team}"
        )
    qb = str(raw.get("quarterback_id") or "").strip()
    rows = raw.get("players")
    if not qb or not isinstance(rows, list) or not rows:
        raise CFBPropUsageInputError(
            f"CFB_PROP_USAGE_TEAM_PLAYERS_REQUIRED:{expected_team}"
        )

    players: list[dict[str, Any]] = []
    profiles: list[PlayerUsageProfile] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_PLAYER_INVALID:{expected_team}"
            )
        player_id = str(row.get("player_id") or "").strip()
        player_name = " ".join(str(row.get("player_name") or "").strip().split())
        position = str(row.get("position") or "").strip().upper()
        team = str(row.get("team") or "").strip()
        if not player_id or not player_name or not position or team != expected_team:
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_PLAYER_IDENTITY_INVALID:{expected_team}"
            )
        norm_name = player_name.casefold()
        if player_id in seen_ids or norm_name in seen_names:
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_PLAYER_DUPLICATE:{expected_team}:{player_id}"
            )
        seen_ids.add(player_id)
        seen_names.add(norm_name)
        if type(row.get("active")) is not bool:
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_ACTIVE_STATE_REQUIRED:{player_id}"
            )
        missing = [field for field in _USAGE_FIELDS if field not in row]
        if missing:
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_SHARE_MISSING:{player_id}:{','.join(missing)}"
            )
        shares = {
            field: _finite_share(
                row[field], f"CFB_PROP_USAGE_SHARE_INVALID:{player_id}:{field}"
            )
            for field in _USAGE_FIELDS
        }
        normalized = {
            "player_id": player_id, "player_name": player_name,
            "position": position, "team": team, "active": row["active"],
            **shares,
        }
        try:
            profiles.append(PlayerUsageProfile(
                player_id=player_id, team=team, position=position,
                active=row["active"], **shares,
            ))
        except (TypeError, ValueError) as exc:
            raise CFBPropUsageInputError(
                f"CFB_PROP_USAGE_PROFILE_INVALID:{player_id}:{exc}"
            ) from exc
        players.append(normalized)

    try:
        team_profile = TeamUsageProfile(
            team=expected_team, players=tuple(profiles), quarterback_id=qb
        )
    except (TypeError, ValueError) as exc:
        raise CFBPropUsageInputError(
            f"CFB_PROP_USAGE_TEAM_PROFILE_INVALID:{expected_team}:{exc}"
        ) from exc
    if team_profile.player(qb).active is not True:
        raise CFBPropUsageInputError(
            f"CFB_PROP_USAGE_STARTING_QB_UNAVAILABLE:{expected_team}:{qb}"
        )
    return {"quarterback_id": qb, "players": players}


def build_live_features(
    *, payload: Mapping[str, Any], input_bytes_sha256: str,
    now: datetime | str, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate a captured usage snapshot and return simulator live features."""
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_SCHEMA_INVALID")
    if str(payload.get("sport") or "").strip().upper() != "CFB":
        raise CFBPropUsageInputError("CFB_PROP_USAGE_SPORT_INVALID")
    _reject_market_fields(payload)
    raw_sha = _hex64(input_bytes_sha256, "CFB_PROP_USAGE_INPUT_SHA256_INVALID")
    current = _aware(now, "CFB_PROP_USAGE_NOW_INVALID")
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_SOURCE_ID_REQUIRED")
    source_updated = _aware(
        payload.get("source_updated_at"), "CFB_PROP_USAGE_SOURCE_UPDATED_AT_INVALID"
    )
    retrieved = _aware(
        payload.get("retrieved_at"), "CFB_PROP_USAGE_RETRIEVED_AT_INVALID"
    )
    asof = _aware(payload.get("asof_ts"), "CFB_PROP_USAGE_ASOF_INVALID")
    if not source_updated <= retrieved <= asof <= current:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_TEMPORAL_ORDER_INVALID")
    if int(max_age_seconds) <= 0:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_MAX_AGE_INVALID")
    if (current - asof).total_seconds() > int(max_age_seconds):
        raise CFBPropUsageInputError("CFB_PROP_USAGE_SNAPSHOT_STALE")

    raw_games = payload.get("games")
    if not isinstance(raw_games, list) or not raw_games:
        raise CFBPropUsageInputError("CFB_PROP_USAGE_GAMES_REQUIRED")
    games: list[dict[str, Any]] = []
    seen_game_ids: set[str] = set()
    seen_event_ids: set[str] = set()
    for raw in raw_games:
        if not isinstance(raw, Mapping):
            raise CFBPropUsageInputError("CFB_PROP_USAGE_GAME_INVALID")
        game_id = str(raw.get("game_id") or "").strip()
        event_id = str(raw.get("provider_event_id") or "").strip()
        start = _aware(raw.get("game_start_ts"), "CFB_PROP_USAGE_GAME_START_INVALID")
        if not game_id or game_id in seen_game_ids:
            raise CFBPropUsageInputError("CFB_PROP_USAGE_GAME_ID_MISSING_OR_DUPLICATE")
        if not event_id or event_id in seen_event_ids:
            raise CFBPropUsageInputError("CFB_PROP_USAGE_PROVIDER_EVENT_ID_MISSING_OR_DUPLICATE")
        seen_game_ids.add(game_id)
        seen_event_ids.add(event_id)
        if asof >= start or current >= start:
            raise CFBPropUsageInputError(f"CFB_PROP_USAGE_GAME_NOT_PREGAME:{game_id}")
        identity = {}
        for field in (
            "home_team", "away_team", "provider_home_team", "provider_away_team"
        ):
            value = str(raw.get(field) or "").strip()
            if not value:
                raise CFBPropUsageInputError(
                    f"CFB_PROP_USAGE_GAME_IDENTITY_MISSING:{game_id}:{field}"
                )
            identity[field] = value
        home_usage = _team_usage(raw.get("home_usage"), expected_team=identity["home_team"])
        away_usage = _team_usage(raw.get("away_usage"), expected_team=identity["away_team"])
        games.append({
            "game_id": game_id,
            "provider_event_id": event_id,
            "game_start_ts": start.isoformat(),
            **identity,
            "home_usage": home_usage,
            "away_usage": away_usage,
        })

    manifest = {
        "schema_version": "CFB_PROP_USAGE_SOURCE_MANIFEST_V1",
        "input_bytes_sha256": raw_sha,
        "source_id": source_id,
        "source_updated_at": source_updated.isoformat(),
        "retrieved_at": retrieved.isoformat(),
        "asof_ts": asof.isoformat(),
        "game_ids": sorted(seen_game_ids),
        "market_fields_consumed": False,
        "usage_synthesized": False,
        "promotion_authority": False,
    }
    manifest_sha = _canonical_sha256(manifest)
    return {
        "schema_version": LIVE_SCHEMA_VERSION,
        "sport": "CFB",
        "asof_ts": asof.isoformat(),
        "source_manifest_sha256": manifest_sha,
        "input_manifest": manifest,
        "games": games,
        "governance": {
            "market_fields_consumed": False,
            "usage_synthesized": False,
            "depth_can_create_usage": False,
            "promotion_authority": False,
            "official_eligible": False,
        },
    }


__all__ = [
    "CFBPropUsageInputError", "DEFAULT_MAX_AGE_SECONDS", "LIVE_SCHEMA_VERSION",
    "SCHEMA_VERSION", "build_live_features", "load_usage_input",
]
