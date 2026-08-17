"""Point-in-time NFL feature cache construction.

Joins each game/team to the latest feature snapshot strictly before kickoff.
Market, price, closing-line, result and outcome fields are prohibited so this
cache can be used as an M2 input without contaminating independent validation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Mapping

_PROHIBITED_TOKENS = (
    "spread", "moneyline", "money_line", "total_line", "implied", "odds",
    "price", "sportsbook", "bookmaker", "closing", "consensus_line",
    "home_score", "away_score", "result", "outcome", "winner", "ats",
)


def _dt(value: Any) -> datetime:
    text = str(value).replace("Z", "+00:00")
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt


def _is_prohibited(key: str) -> bool:
    name = key.lower()
    return any(token in name for token in _PROHIBITED_TOKENS)


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    for key in snapshot:
        if _is_prohibited(str(key)):
            raise ValueError(f"POINT_IN_TIME_PROHIBITED_FIELD:{key}")
    if not str(snapshot.get("team", "")).strip():
        raise ValueError("POINT_IN_TIME_TEAM_MISSING")
    _dt(snapshot.get("feature_asof_ts"))


def build_game_feature_rows(
    games: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return two rows per game, each joined to a strictly-prior team snapshot."""
    snapshot_rows = [dict(row) for row in snapshots]
    for row in snapshot_rows:
        _validate_snapshot(row)

    by_team: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot_rows:
        by_team.setdefault(str(row["team"]), []).append(row)
    for rows in by_team.values():
        rows.sort(key=lambda r: _dt(r["feature_asof_ts"]))

    out: list[dict[str, Any]] = []
    for raw_game in games:
        game = dict(raw_game)
        start = _dt(game.get("game_start_ts"))
        for side, team_key in (("home", "home_team"), ("away", "away_team")):
            team = str(game.get(team_key, "")).strip()
            if not team:
                raise ValueError(f"POINT_IN_TIME_GAME_TEAM_MISSING:{team_key}")
            candidates = [r for r in by_team.get(team, []) if _dt(r["feature_asof_ts"]) < start]
            if not candidates:
                raise ValueError(f"POINT_IN_TIME_SNAPSHOT_MISSING:{team}")
            chosen = candidates[-1]
            row = dict(chosen)
            row.update({
                "game_id": game.get("game_id"),
                "season": game.get("season"),
                "week": game.get("week"),
                "game_start_ts": start.isoformat(),
                "team": team,
                "opponent": str(game.get("away_team" if side == "home" else "home_team", "")),
                "side": side,
            })
            out.append(row)
    return out


def _valid_sha256(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def build_cache_manifest(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_sha256: str,
    source_name: str,
) -> dict[str, Any]:
    if not _valid_sha256(source_sha256):
        raise ValueError("SOURCE_SHA256_INVALID")
    if not str(source_name).strip():
        raise ValueError("SOURCE_NAME_REQUIRED")

    materialized = [dict(row) for row in rows]
    canonical_rows = sorted(
        materialized,
        key=lambda r: (str(r.get("game_id", "")), str(r.get("team", "")), str(r.get("feature_asof_ts", ""))),
    )
    payload = json.dumps(canonical_rows, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    cache_sha256 = hashlib.sha256(payload).hexdigest()
    seasons = sorted({int(r["season"]) for r in materialized if r.get("season") not in (None, "")})
    return {
        "provenance": "POINT_IN_TIME_REAL_HISTORY",
        "source_name": str(source_name),
        "source_sha256": source_sha256.lower(),
        "cache_sha256": cache_sha256,
        "row_count": len(materialized),
        "seasons": seasons,
    }
