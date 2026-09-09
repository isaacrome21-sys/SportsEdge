from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from .context_autopull import NFLContextError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SpecialTeamsSnapshot:
    team_id: str
    kicker_active: bool | None
    returner_active: bool | None
    field_goal_pct_40_49: float | None
    field_goal_pct_50_plus: float | None
    touchback_rate: float | None
    punt_net_yards: float | None
    punt_return_allowed_yards: float | None
    kick_return_allowed_yards: float | None


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NFLContextError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NFLContextError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _rate(value: Any, field: str) -> float | None:
    if value in (None, ""):
        return None
    x = float(value)
    if not 0.0 <= x <= 1.0:
        raise NFLContextError(f"{field} outside [0,1]")
    return x


def build_special_teams_snapshot(row: Mapping[str, Any]) -> SpecialTeamsSnapshot:
    team_id = str(row.get("team_id") or "").strip().upper()
    if not team_id:
        raise NFLContextError("special teams team_id required")
    return SpecialTeamsSnapshot(
        team_id=team_id,
        kicker_active=None if row.get("kicker_active") is None else bool(row.get("kicker_active")),
        returner_active=None if row.get("returner_active") is None else bool(row.get("returner_active")),
        field_goal_pct_40_49=_rate(row.get("field_goal_pct_40_49"), "field_goal_pct_40_49"),
        field_goal_pct_50_plus=_rate(row.get("field_goal_pct_50_plus"), "field_goal_pct_50_plus"),
        touchback_rate=_rate(row.get("touchback_rate"), "touchback_rate"),
        punt_net_yards=None if row.get("punt_net_yards") in (None, "") else float(row.get("punt_net_yards")),
        punt_return_allowed_yards=None if row.get("punt_return_allowed_yards") in (None, "") else float(row.get("punt_return_allowed_yards")),
        kick_return_allowed_yards=None if row.get("kick_return_allowed_yards") in (None, "") else float(row.get("kick_return_allowed_yards")),
    )


def build_special_teams_provider(
    *,
    game_id: str,
    as_of: Any,
    kickoff_ts: Any,
    source_uri: str,
    source_sha256: str,
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    game = str(game_id or "").strip()
    if not game:
        raise NFLContextError("special teams game_id required")
    if not str(source_uri).startswith("https://"):
        raise NFLContextError("special teams source_uri must be https")
    digest = str(source_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise NFLContextError("special teams source_sha256 invalid")
    pit = _utc(as_of, "as_of")
    kickoff = _utc(kickoff_ts, "kickoff_ts")
    if pit >= kickoff:
        raise NFLContextError(f"NFL_SPECIAL_TEAMS_NOT_PREGAME:{game}")
    snapshots = [asdict(build_special_teams_snapshot(r)) for r in rows]
    team_ids = [row["team_id"] for row in snapshots]
    if len(team_ids) != len(set(team_ids)):
        raise NFLContextError("special teams duplicate team_id")
    payload = {"game_id": game, "teams": snapshots}
    return {
        "status": "AVAILABLE" if rows else "MISSING",
        "payload": payload,
        "source_name": "OFFICIAL_ROSTERS+PIT_SPECIAL_TEAMS_HISTORY",
        "source_uri": source_uri,
        "source_sha256": digest,
        "observed_at": pit,
        "kickoff_ts": kickoff.isoformat(),
    }
