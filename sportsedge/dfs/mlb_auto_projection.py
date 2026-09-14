from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

from .mlb_joint_v2 import build_mlb_joint_path_snapshot_v2
from .sources.mlb_roster_stats import MLBSeasonStatsClient
from .types import DKPlayer


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("MLB_DFS_AUTO_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def build_mlb_auto_projection_snapshot(
    *,
    players: Iterable[DKPlayer],
    slate_start: datetime,
    as_of: datetime | None = None,
    paths: int = 5000,
    seed: int | None = None,
    stats_client: MLBSeasonStatsClient | None = None,
) -> dict:
    """Build pre-lock MLB DFS paths from confirmed context and live StatsAPI stats.

    This live source is valid for a current pre-lock decision only. It is not an
    archival replay source: historical reconstruction must use frozen PIT artifacts
    rather than today's season totals.
    """
    pool = [p for p in players if not p.is_disabled]
    if not pool:
        raise ValueError("MLB_DFS_AUTO_PLAYER_POOL_EMPTY")
    lock = _utc(slate_start)
    pit = _utc(as_of or datetime.now(timezone.utc))
    if pit >= lock:
        raise ValueError("MLB_DFS_AUTO_NOT_PREGAME")

    teams = sorted({p.team for p in pool if p.team})
    for team in teams:
        hitters = [p for p in pool if p.team == team and not p.is_pitcher]
        pitchers = [p for p in pool if p.team == team and p.is_pitcher]
        if len(hitters) != 9 or any(not p.raw.get("mlb_confirmed_lineup") for p in hitters):
            raise ValueError(f"MLB_DFS_AUTO_CONFIRMED_LINEUP_REQUIRED:{team}:{len(hitters)}")
        if len(pitchers) != 1 or not pitchers[0].raw.get("mlb_probable_starter"):
            raise ValueError(f"MLB_DFS_AUTO_PROBABLE_STARTER_REQUIRED:{team}:{len(pitchers)}")

    client = stats_client or MLBSeasonStatsClient()
    stats = client.build_snapshot(players=pool, season=lock.year)
    if seed is None:
        seed_payload = {
            "sport": "MLB",
            "slate_start": lock.isoformat(),
            "stats_sha": stats.get("source_manifest_sha256"),
            "player_ids": sorted(p.player_id for p in pool),
        }
        seed = int(
            sha256(
                json.dumps(seed_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:8],
            16,
        )

    snapshot = build_mlb_joint_path_snapshot_v2(
        players=pool,
        stats_snapshot=stats,
        as_of=pit,
        paths=int(paths),
        seed=int(seed),
    )
    diagnostics = dict(snapshot.get("diagnostics") or {})
    diagnostics.update(
        {
            "auto_projection": True,
            "stats_source": stats.get("source"),
            "stats_source_manifest_sha256": stats.get("source_manifest_sha256"),
            "stats_provenance_mode": stats.get("provenance_mode"),
            "stats_player_count": stats.get("player_count"),
            "stats_coverage": stats.get("coverage"),
            "projection_authority": "RESEARCH_ONLY_UNVALIDATED",
            "historical_replay_authority": False,
        }
    )
    snapshot["diagnostics"] = diagnostics
    snapshot["auto_projection_context"] = {
        "as_of_utc": pit.isoformat(),
        "slate_start_utc": lock.isoformat(),
        "season": lock.year,
        "stats_source_manifest_sha256": stats.get("source_manifest_sha256"),
    }
    return snapshot
