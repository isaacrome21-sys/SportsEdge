"""PIT-safe historical NHL roster-role shares for coherent player simulations.

This layer derives transparent empirical workload shares from already-observed
pregame-eligible history. It deliberately does not contain sportsbook inputs,
proprietary weights, or performance claims. Callers remain responsible for
supplying history captured before the target game's puck drop.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Iterable


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class NHLPlayerGameRoleObservation:
    game_id: str
    player_id: str
    team_id: str
    puck_drop: str
    settled_at: str
    source: str
    source_version: str
    shots_on_goal: int
    goals: int
    primary_assists: int
    secondary_assists: int
    games_played: int = 1

    def __post_init__(self) -> None:
        puck, settled = _utc(self.puck_drop), _utc(self.settled_at)
        if settled <= puck:
            raise ValueError("settled role observation must postdate puck drop")
        if not all((self.game_id, self.player_id, self.team_id, self.source, self.source_version)):
            raise ValueError("role observation identity/provenance required")
        values = (self.shots_on_goal, self.goals, self.primary_assists,
                  self.secondary_assists, self.games_played)
        if any((not isinstance(x, int)) or x < 0 for x in values):
            raise ValueError("role counts must be nonnegative integers")
        if self.games_played != 1:
            raise ValueError("one observation must represent one player-game")


@dataclass(frozen=True)
class NHLHistoricalRoleShare:
    player_id: str
    team_id: str
    cutoff: str
    source: str
    version: str
    games: int
    shot_weight: float
    goal_weight: float
    primary_assist_weight: float
    secondary_assist_weight: float
    history_sha256: str

    def __post_init__(self) -> None:
        _utc(self.cutoff)
        if self.games <= 0 or not self.history_sha256:
            raise ValueError("positive history and provenance required")
        weights = (self.shot_weight, self.goal_weight, self.primary_assist_weight,
                   self.secondary_assist_weight)
        if any((not math.isfinite(x)) or x < 0 for x in weights):
            raise ValueError("role weights must be finite and nonnegative")


def eligible_role_history(observations: Iterable[NHLPlayerGameRoleObservation], *,
                          cutoff: str, team_id: str | None = None) -> tuple[NHLPlayerGameRoleObservation, ...]:
    cut = _utc(cutoff)
    rows = [r for r in observations if _utc(r.settled_at) < cut and
            (team_id is None or r.team_id == team_id)]
    return tuple(sorted(rows, key=lambda r: (_utc(r.puck_drop), r.game_id, r.player_id)))


def role_history_sha256(rows: Iterable[NHLPlayerGameRoleObservation]) -> str:
    payload = [r.__dict__ for r in sorted(rows, key=lambda r: (r.puck_drop, r.game_id, r.player_id))]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def fit_empirical_role_shares(observations: Iterable[NHLPlayerGameRoleObservation], *,
                              cutoff: str, team_id: str, version: str,
                              min_games: int = 1) -> tuple[NHLHistoricalRoleShare, ...]:
    """Return raw empirical role weights using only history settled before cutoff.

    Counts are intentionally not smoothed here: a future calibrated role model can
    replace these weights without changing the PIT contract. Players below
    ``min_games`` are omitted rather than receiving invented priors.
    """
    if not version or min_games < 1:
        raise ValueError("version and positive min_games required")
    rows = eligible_role_history(observations, cutoff=cutoff, team_id=team_id)
    if not rows:
        return ()
    digest = role_history_sha256(rows)
    by_player: dict[str, list[NHLPlayerGameRoleObservation]] = {}
    for row in rows:
        by_player.setdefault(row.player_id, []).append(row)
    out = []
    for player_id in sorted(by_player):
        history = by_player[player_id]
        games = sum(r.games_played for r in history)
        if games < min_games:
            continue
        sources = sorted({f"{r.source}@{r.source_version}" for r in history})
        out.append(NHLHistoricalRoleShare(
            player_id=player_id, team_id=team_id, cutoff=cutoff,
            source="+".join(sources), version=version, games=games,
            shot_weight=sum(r.shots_on_goal for r in history) / games,
            goal_weight=sum(r.goals for r in history) / games,
            primary_assist_weight=sum(r.primary_assists for r in history) / games,
            secondary_assist_weight=sum(r.secondary_assists for r in history) / games,
            history_sha256=digest,
        ))
    return tuple(out)
