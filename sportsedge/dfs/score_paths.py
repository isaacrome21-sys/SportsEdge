from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from .scoring import dk_scores_from_samples
from .types import DKPlayer


@dataclass(frozen=True)
class AlignedScorePaths:
    sport: str
    path_set_id: str
    path_count: int
    player_scores: dict[str, tuple[float, ...]]
    source: str

    def lineup_scores(self, player_ids: Iterable[str]) -> tuple[float, ...]:
        ids = tuple(dict.fromkeys(str(pid) for pid in player_ids))
        if not ids:
            raise ValueError("DFS_LINEUP_PATH_IDS_EMPTY")
        missing = [pid for pid in ids if pid not in self.player_scores]
        if missing:
            raise ValueError("DFS_LINEUP_PATHS_MISSING:" + ",".join(sorted(missing)))
        return tuple(
            sum(self.player_scores[pid][idx] for pid in ids)
            for idx in range(self.path_count)
        )


def load_aligned_score_paths(
    path: str | Path,
    players: Iterable[DKPlayer],
    sport: str,
) -> AlignedScorePaths:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("DFS_PATH_SNAPSHOT_SHAPE_INVALID")
    path_set_id = str(payload.get("path_set_id") or "").strip()
    if not path_set_id:
        raise ValueError("DFS_PATH_SET_ID_REQUIRED")
    rows = payload.get("players")
    if not isinstance(rows, list):
        raise ValueError("DFS_PATH_PLAYERS_REQUIRED")
    by_id = {p.player_id: p for p in players}
    by_name_team = {(p.name.casefold(), p.team): p for p in players}
    scores: dict[str, tuple[float, ...]] = {}
    expected_count: int | None = None
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("samples"), list):
            continue
        pid = str(row.get("player_id") or row.get("playerDkId") or "")
        player = by_id.get(pid)
        if player is None:
            player = by_name_team.get((str(row.get("name") or "").casefold(), str(row.get("team") or "").upper()))
        if player is None:
            continue
        player_path_set = str(row.get("path_set_id") or path_set_id).strip()
        if player_path_set != path_set_id:
            raise ValueError(f"DFS_PATH_SET_MISMATCH:{player.player_id}")
        player_scores = dk_scores_from_samples(player, sport, row["samples"])
        if expected_count is None:
            expected_count = len(player_scores)
        elif len(player_scores) != expected_count:
            raise ValueError(f"DFS_PATH_COUNT_MISMATCH:{player.player_id}:{len(player_scores)}:{expected_count}")
        scores[player.player_id] = player_scores
    if expected_count is None or expected_count < 1000:
        raise ValueError("DFS_ALIGNED_PATHS_INSUFFICIENT")
    active = [p for p in players if not p.is_disabled]
    coverage = sum(1 for p in active if p.player_id in scores) / max(1, len(active))
    if coverage < 0.90:
        raise ValueError(f"DFS_PATH_COVERAGE_TOO_LOW:{coverage:.3f}")
    return AlignedScorePaths(
        sport=sport.upper(),
        path_set_id=path_set_id,
        path_count=expected_count,
        player_scores=scores,
        source=str(payload.get("source") or "SPORTSEDGE_JOINT_PATHS"),
    )
