"""Manual/phone CFB depth input gate for the frozen prop runtime.

This layer validates already-captured point-in-time depth snapshots and binds them
into the live-feature manifest. It never fetches a source, invents usage, changes
numeric usage shares, reads sportsbook prices, or grants promotion authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .depth_chart_source import (
    CFBDepthSourceError,
    CORROBORATION_SOURCE_ID,
    POLICY_SHA256,
    require_player_depth_usable,
    validate_depth_snapshot,
)

SCHEMA_VERSION = "CFB_PROP_MANUAL_DEPTH_INPUT_V1"
_FORBIDDEN_KEYS = frozenset({
    "price", "prices", "odds", "american_odds", "decimal_odds", "line",
    "market", "markets", "spread", "total", "moneyline", "vig", "no_vig",
})


class CFBPropManualDepthError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CFBPropManualDepthError("CFB_PROP_DEPTH_CANONICAL_INPUT_INVALID") from exc
    return sha256(raw).hexdigest()


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBPropManualDepthError(code)
    return text


def _reject_market_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if name in _FORBIDDEN_KEYS or "sportsbook" in name:
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_MARKET_FIELD_FORBIDDEN:{path}.{key}")
            _reject_market_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_market_fields(child, f"{path}[{idx}]")


def load_manual_depth_input(path: str | Path) -> tuple[dict[str, Any], str]:
    p = Path(path)
    try:
        raw = p.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_INPUT_INVALID") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_SCHEMA_INVALID")
    _reject_market_fields(payload)
    return dict(payload), sha256(raw).hexdigest()


def _usage_players(game: Mapping[str, Any], side: str) -> tuple[str, dict[str, Mapping[str, Any]], str]:
    team = str(game.get(f"{side}_team") or "").strip()
    usage = game.get(f"{side}_usage")
    if not team or not isinstance(usage, Mapping):
        raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_TEAM_USAGE_REQUIRED:{side}")
    rows = usage.get("players")
    if not isinstance(rows, list) or not rows:
        raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_USAGE_PLAYERS_REQUIRED:{team}")
    players: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_USAGE_PLAYER_INVALID:{team}")
        player_id = str(row.get("player_id") or "").strip()
        if not player_id or player_id in players:
            raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_USAGE_PLAYER_ID_INVALID:{team}")
        players[player_id] = row
    qb = str(usage.get("quarterback_id") or "").strip()
    if not qb:
        raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_STARTING_QB_REQUIRED:{team}")
    return team, players, qb


def bind_manual_depth_to_live_features(
    *, live_features: Mapping[str, Any], manual_input: Mapping[str, Any], manual_bytes_sha256: str,
) -> dict[str, Any]:
    """Validate manual depth evidence and bind it to live features without inventing usage."""
    if not isinstance(live_features, Mapping) or str(live_features.get("sport") or "").upper() != "CFB":
        raise CFBPropManualDepthError("CFB_PROP_DEPTH_LIVE_FEATURES_INVALID")
    if not isinstance(manual_input, Mapping) or manual_input.get("schema_version") != SCHEMA_VERSION:
        raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_SCHEMA_INVALID")
    _reject_market_fields(manual_input)
    manual_sha = _hex64(manual_bytes_sha256, "CFB_PROP_MANUAL_DEPTH_BYTES_SHA256_INVALID")

    decision_time = str(manual_input.get("decision_time") or "").strip()
    entries = manual_input.get("teams")
    if not decision_time or not isinstance(entries, list) or not entries:
        raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_TEAMS_REQUIRED")
    by_team: dict[str, Mapping[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_TEAM_INVALID")
        team_id = str(raw.get("team_id") or "").strip()
        if not team_id or team_id in by_team:
            raise CFBPropManualDepthError("CFB_PROP_MANUAL_DEPTH_TEAM_ID_INVALID")
        by_team[team_id] = raw

    games = live_features.get("games")
    if not isinstance(games, list) or not games:
        raise CFBPropManualDepthError("CFB_PROP_DEPTH_LIVE_FEATURE_GAMES_REQUIRED")

    validated_sources: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, Mapping):
            raise CFBPropManualDepthError("CFB_PROP_DEPTH_LIVE_FEATURE_GAME_INVALID")
        game_start = str(game.get("game_start_ts") or "").strip()
        if not game_start:
            raise CFBPropManualDepthError("CFB_PROP_DEPTH_GAME_START_REQUIRED")
        for side in ("home", "away"):
            team, usage_players, starting_qb = _usage_players(game, side)
            raw_entry = by_team.get(team)
            if not isinstance(raw_entry, Mapping):
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_TEAM_SNAPSHOT_REQUIRED:{team}")
            primary = raw_entry.get("primary_snapshot")
            if not isinstance(primary, Mapping):
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_PRIMARY_SNAPSHOT_REQUIRED:{team}")
            try:
                checked = validate_depth_snapshot(
                    primary,
                    previous_game_end=str(raw_entry.get("previous_game_end") or ""),
                    decision_time=decision_time,
                    target_game_start=game_start,
                    expected_team_id=team,
                    expected_content_sha256=str(raw_entry.get("expected_content_sha256") or ""),
                )
            except CFBDepthSourceError as exc:
                raise CFBPropManualDepthError(str(exc)) from exc

            corroboration = raw_entry.get("corroboration")
            if not isinstance(corroboration, Mapping):
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_CORROBORATION_REQUIRED:{team}")
            if str(corroboration.get("source_id") or "").strip() != CORROBORATION_SOURCE_ID:
                raise CFBPropManualDepthError("CFB_DEPTH_CORROBORATION_SOURCE_INVALID")
            starters = corroboration.get("starter_player_ids")
            if not isinstance(starters, Mapping):
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_CORROBORATING_STARTERS_REQUIRED:{team}")

            depth_players = {str(row["player_id"]): row for row in checked["players"]}
            # Depth does not synthesize shares. It only rejects contradictions with
            # the independently supplied usage feature snapshot.
            for player_id, depth_player in depth_players.items():
                if depth_player.get("unavailable") is True and player_id in usage_players and usage_players[player_id].get("active") is True:
                    raise CFBPropManualDepthError("PLAYER_UNAVAILABLE")
                if int(depth_player.get("depth_rank", 0)) == 1:
                    position = str(depth_player.get("position") or "").strip().upper()
                    starter_id = str(starters.get(position) or "").strip()
                    try:
                        require_player_depth_usable(
                            primary_player=depth_player,
                            corroborating_source_id=CORROBORATION_SOURCE_ID,
                            corroborating_starter_player_id=starter_id,
                        )
                    except CFBDepthSourceError as exc:
                        raise CFBPropManualDepthError(str(exc)) from exc

            qb_depth = depth_players.get(starting_qb)
            if qb_depth is None or int(qb_depth.get("depth_rank", 0)) != 1 or qb_depth.get("unavailable") is True:
                raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_STARTING_QB_UNCONFIRMED:{team}:{starting_qb}")

            validated_sources.append({
                "team_id": team,
                "content_sha256": checked["content_sha256"],
                "source_updated_at": checked["source_updated_at"],
                "retrieved_at": checked["retrieved_at"],
                "policy_sha256": checked["policy_sha256"],
            })

    expected_teams = {str(game.get("home_team") or "").strip() for game in games} | {str(game.get("away_team") or "").strip() for game in games}
    extras = set(by_team) - expected_teams
    if extras:
        raise CFBPropManualDepthError(f"CFB_PROP_DEPTH_UNEXPECTED_TEAM:{sorted(extras)[0]}")

    prior_source = _hex64(
        live_features.get("source_manifest_sha256"),
        "CFB_PROP_LIVE_FEATURE_SOURCE_SHA256_INVALID",
    )
    manifest = {
        "schema_version": "CFB_PROP_LIVE_INPUT_MANIFEST_V1",
        "prior_live_feature_source_manifest_sha256": prior_source,
        "manual_depth_bytes_sha256": manual_sha,
        "depth_policy_sha256": POLICY_SHA256,
        "validated_depth_sources": sorted(validated_sources, key=lambda row: row["team_id"]),
    }
    out = dict(live_features)
    out["source_manifest_sha256"] = _canonical_sha256(manifest)
    out["input_manifest_sha256"] = out["source_manifest_sha256"]
    out["depth_input_manifest"] = manifest
    out["depth_input_can_create_usage"] = False
    out["depth_input_can_promote"] = False
    return out


__all__ = [
    "CFBPropManualDepthError", "SCHEMA_VERSION", "bind_manual_depth_to_live_features",
    "load_manual_depth_input",
]
