from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .auto_context_source import (
    _fetch_schedule,
    _kickoff,
    _team,
    build_nfl_auto_game_context,
)
from .auto_personnel_source import build_depth_chart_personnel_provider
from .context_autopull import ContextObservation, NFLContextError
from .run_it_context import build_run_it_context


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise NFLContextError(f"{field} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NFLContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def discover_nfl_auto_games(
    *,
    as_of: Any,
    min_lead_minutes: int = 0,
    horizon_minutes: int = 24 * 60,
    game_types: Iterable[str] = ("REG",),
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Discover upcoming NFL games from the same nflverse schedule used by M2.

    Only identity/schedule metadata is returned. Betting columns that happen to
    coexist in the upstream CSV are never copied into the AUTO context lane.
    """
    pit = _utc(as_of, "as_of")
    if isinstance(min_lead_minutes, bool) or not isinstance(min_lead_minutes, int):
        raise NFLContextError("min_lead_minutes must be integer")
    if isinstance(horizon_minutes, bool) or not isinstance(horizon_minutes, int):
        raise NFLContextError("horizon_minutes must be integer")
    if min_lead_minutes < 0 or horizon_minutes < min_lead_minutes:
        raise NFLContextError("AUTO slate window invalid")
    allowed = {str(value or "").strip().upper() for value in game_types}
    allowed.discard("")
    if not allowed:
        raise NFLContextError("AUTO slate game_types empty")

    rows, schedule_sha = _fetch_schedule(opener=opener)
    lower = pit + timedelta(minutes=min_lead_minutes)
    upper = pit + timedelta(minutes=horizon_minutes)
    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        game_type = str(row.get("game_type") or "REG").strip().upper()
        if game_type not in allowed:
            continue
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        kickoff = _kickoff(row)
        if not lower <= kickoff <= upper:
            continue
        if game_id in seen:
            raise NFLContextError(f"duplicate NFL schedule game_id:{game_id}")
        seen.add(game_id)
        home = _team(row.get("home_team"))
        away = _team(row.get("away_team"))
        if not home or not away or home == away:
            raise NFLContextError(f"NFL schedule team identity invalid:{game_id}")
        discovered.append(
            {
                "game_id": game_id,
                "game_type": game_type,
                "season": None if row.get("season") in (None, "") else int(float(row["season"])),
                "week": None if row.get("week") in (None, "") else int(float(row["week"])),
                "kickoff_ts": kickoff.isoformat(),
                "away_team_id": away,
                "home_team_id": home,
            }
        )
    discovered.sort(key=lambda item: (item["kickoff_ts"], item["game_id"]))
    return {
        "schema_version": 1,
        "sport": "NFL",
        "as_of_utc": pit.isoformat(),
        "min_lead_minutes": min_lead_minutes,
        "horizon_minutes": horizon_minutes,
        "game_types": sorted(allowed),
        "schedule_source_sha256": schedule_sha,
        "games": discovered,
    }


def build_nfl_auto_context_slate(
    *,
    as_of: Any,
    mode: str = "AUTO",
    min_lead_minutes: int = 0,
    horizon_minutes: int = 24 * 60,
    game_types: Iterable[str] = ("REG",),
    manual_observations_by_game: Mapping[str, Iterable[ContextObservation]] | None = None,
    depth_chart_rows: Iterable[Mapping[str, Any]] | None = None,
    depth_chart_source_uri: str | None = None,
    depth_chart_source_sha256: str | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Discover an upcoming slate then collect each game's canonical context.

    AUTO needs no operator game list. HYBRID may supply optional manual class
    overrides keyed by game_id. Optional frozen PIT depth-chart rows enrich the
    personnel-known flags without synthesizing personnel rates. MANUAL is
    intentionally excluded because slate discovery itself is automatic.
    """
    requested = str(mode or "").strip().upper()
    if requested not in {"AUTO", "HYBRID"}:
        raise NFLContextError("AUTO slate mode must be AUTO or HYBRID")
    plan = discover_nfl_auto_games(
        as_of=as_of,
        min_lead_minutes=min_lead_minutes,
        horizon_minutes=horizon_minutes,
        game_types=game_types,
        opener=opener,
    )
    manual = dict(manual_observations_by_game or {})
    depth = None if depth_chart_rows is None else [dict(row) for row in depth_chart_rows]
    if depth is not None and (not depth_chart_source_uri or not depth_chart_source_sha256):
        raise NFLContextError("depth chart provenance required")

    bundles: list[dict[str, Any]] = []
    for discovered in plan["games"]:
        game_id = str(discovered["game_id"])
        game = build_nfl_auto_game_context(
            game_id=game_id,
            as_of=as_of,
            opener=opener,
        )
        if depth is not None:
            personnel = build_depth_chart_personnel_provider(
                game_id=game_id,
                team_ids=(str(game.get("home_team_id") or ""), str(game.get("away_team_id") or "")),
                as_of=as_of,
                source_uri=str(depth_chart_source_uri),
                source_sha256=str(depth_chart_source_sha256),
                rows=depth,
            )
            if personnel is not None:
                game["auto_personnel_provider"] = personnel
        bundles.append(
            build_run_it_context(
                mode=requested,
                game=game,
                as_of=as_of,
                manual_observations=list(manual.get(game_id, ())),
                opener=opener,
            )
        )
    return {
        "schema_version": 1,
        "sport": "NFL",
        "collection_mode": requested,
        "as_of_utc": plan["as_of_utc"],
        "schedule_source_sha256": plan["schedule_source_sha256"],
        "depth_chart_source_sha256": depth_chart_source_sha256 if depth is not None else None,
        "game_count": len(bundles),
        "games": bundles,
        "model_p_eligible": False,
        "truth_gate_eligible": False,
        "validation_status": "UNVALIDATED_CONTEXT_SIDE_CAR",
    }
