from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Iterable

from .cfb_joint import build_cfb_joint_path_snapshot
from .sources.cfb_espn_history import EspnCFBHistoryClient
from .types import DKPlayer


def build_cfb_auto_projection_snapshot(
    *,
    players: Iterable[DKPlayer],
    slate_start: datetime,
    as_of: datetime | None = None,
    paths: int = 5000,
    seed: int | None = None,
    max_history_games: int = 6,
    history_client: EspnCFBHistoryClient | None = None,
) -> dict:
    pool = [p for p in players if not p.is_disabled]
    if not pool:
        raise ValueError("CFB_DFS_AUTO_PLAYER_POOL_EMPTY")
    if slate_start.tzinfo is None or slate_start.utcoffset() is None:
        raise ValueError("CFB_DFS_AUTO_SLATE_TIMEZONE_REQUIRED")
    lock = slate_start.astimezone(timezone.utc)
    pit = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if pit >= lock:
        raise ValueError("CFB_DFS_AUTO_NOT_PREGAME")
    client = history_client or EspnCFBHistoryClient()
    history = client.build_history(
        players=pool,
        slate_start=lock,
        max_games=max_history_games,
        include_prior_season=True,
    )
    if history.get("player_count", 0) < 2:
        raise ValueError("CFB_DFS_AUTO_HISTORY_TOO_SPARSE")
    if seed is None:
        seed_payload = {
            "sport": "CFB",
            "slate_start": lock.isoformat(),
            "history_manifest": history.get("source_manifest_sha256"),
            "player_ids": sorted(p.player_id for p in pool),
        }
        seed = int(sha256(json.dumps(seed_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8], 16)
    snapshot = build_cfb_joint_path_snapshot(
        players=pool,
        history_payload=history,
        as_of=pit,
        paths=int(paths),
        seed=int(seed),
    )
    diagnostics = dict(snapshot.get("diagnostics") or {})
    diagnostics.update({
        "auto_projection": True,
        "history_source": history.get("source"),
        "history_source_manifest_sha256": history.get("source_manifest_sha256"),
        "history_player_count": history.get("player_count"),
        "targets_estimated_rows": history.get("targets_estimated_rows"),
        "projection_authority": "RESEARCH_ONLY_UNVALIDATED",
    })
    snapshot["diagnostics"] = diagnostics
    snapshot["auto_projection_context"] = {
        "as_of_utc": pit.isoformat(),
        "slate_start_utc": lock.isoformat(),
        "season": history.get("season"),
        "teams": history.get("teams"),
        "source_manifest_sha256": history.get("source_manifest_sha256"),
    }
    return snapshot
