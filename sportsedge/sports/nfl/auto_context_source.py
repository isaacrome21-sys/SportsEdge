from __future__ import annotations

from datetime import datetime, time, timezone
from hashlib import sha256
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...source_lineage import canonical_json_sha256
from .context_autopull import NFLContextError
from .context_providers import haversine_km
from .history import NFLVERSE_SCHEDULE_CSV, parse_schedule_csv
from .stadium_registry import load_stadium_registry

_EASTERN = ZoneInfo("America/New_York")
_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}


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


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


def _kickoff(row: Mapping[str, Any]) -> datetime:
    explicit = row.get("game_start_ts") or row.get("start_time")
    if explicit not in (None, ""):
        return _utc(explicit, "NFL schedule kickoff")
    day = str(row.get("gameday") or row.get("game_date") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        raise NFLContextError(f"NFL schedule kickoff missing:{row.get('game_id')}")
    try:
        local = datetime.combine(
            datetime.fromisoformat(day[:10]).date(),
            time.fromisoformat(clock),
            tzinfo=_EASTERN,
        )
    except ValueError as exc:
        raise NFLContextError(f"NFL schedule kickoff invalid:{row.get('game_id')}") from exc
    return local.astimezone(timezone.utc)


def _fetch_schedule(*, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str]:
    req = Request(
        NFLVERSE_SCHEDULE_CSV,
        headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"},
    )
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
        text = raw.decode("utf-8-sig")
    except Exception as exc:
        raise NFLContextError("NFLVERSE schedule fetch failed") from exc
    rows = parse_schedule_csv(text)
    if not rows:
        raise NFLContextError("NFLVERSE schedule empty")
    return rows, sha256(raw).hexdigest()


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise NFLContextError("NFL schedule integer field invalid") from exc


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("&", "and").split())


def _neutral_state(row: Mapping[str, Any]) -> bool | None:
    location = str(row.get("location") or "").strip().lower()
    if location in {"neutral", "international"}:
        return True
    if location in {"home", "away"}:
        return False
    return None


def _stadium_id_for_row(row: Mapping[str, Any], registry: Mapping[str, Any]) -> str | None:
    stadium_name = _norm_name(row.get("stadium"))
    if stadium_name:
        matches = [
            stadium_id
            for stadium_id, stadium in (registry.get("stadiums") or {}).items()
            if _norm_name(stadium.name) == stadium_name
        ]
        if len(matches) == 1:
            return str(matches[0])
        if len(matches) > 1:
            raise NFLContextError("NFL stadium name maps to multiple registry rows")
    if _neutral_state(row) is False:
        return (registry.get("team_to_stadium") or {}).get(_team(row.get("home_team")))
    return None


def _roof_decision(row: Mapping[str, Any]) -> str | None:
    raw = str(row.get("roof") or "").strip().lower()
    if raw in {"closed", "retractable roof - closed"}:
        return "CLOSED"
    if raw in {"open", "retractable roof - open"}:
        return "OPEN"
    return None


def _row_has_team(row: Mapping[str, Any], team_id: str) -> bool:
    return team_id in {_team(row.get("home_team")), _team(row.get("away_team"))}


def _previous_game(
    *,
    rows: list[dict[str, Any]],
    team_id: str,
    current_game_id: str,
    current_kickoff: datetime,
) -> tuple[Mapping[str, Any] | None, datetime | None]:
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in rows:
        if str(row.get("game_id") or "").strip() == current_game_id or not _row_has_team(row, team_id):
            continue
        try:
            start = _kickoff(row)
        except NFLContextError:
            continue
        if start < current_kickoff:
            eligible.append((start, row))
    if not eligible:
        return None, None
    start, row = max(eligible, key=lambda item: item[0])
    return row, start


def _road_streak(
    *,
    rows: list[dict[str, Any]],
    team_id: str,
    current_game_id: str,
    current_kickoff: datetime,
    current_row: Mapping[str, Any],
) -> int | None:
    neutral = _neutral_state(current_row)
    if neutral is not False:
        return None
    if _team(current_row.get("home_team")) == team_id:
        return 0
    if _team(current_row.get("away_team")) != team_id:
        raise NFLContextError("team not present in current NFL schedule row")
    prior: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in rows:
        if str(row.get("game_id") or "").strip() == current_game_id or not _row_has_team(row, team_id):
            continue
        try:
            start = _kickoff(row)
        except NFLContextError:
            continue
        if start < current_kickoff:
            prior.append((start, row))
    streak = 1
    for _, row in sorted(prior, key=lambda item: item[0], reverse=True):
        if _neutral_state(row) is not False:
            break
        if _team(row.get("away_team")) == team_id:
            streak += 1
            continue
        break
    return streak


def _stadium_coords(
    row: Mapping[str, Any] | None,
    registry: Mapping[str, Any],
) -> tuple[float, float, str] | None:
    if row is None:
        return None
    stadium_id = _stadium_id_for_row(row, registry)
    if not stadium_id:
        return None
    stadium = (registry.get("stadiums") or {}).get(stadium_id)
    if stadium is None:
        return None
    return float(stadium.lat), float(stadium.lon), str(stadium.timezone_name)


def _tz_shift_hours(
    previous: tuple[float, float, str] | None,
    current: tuple[float, float, str] | None,
    *,
    previous_kickoff: datetime | None,
    current_kickoff: datetime,
) -> int | None:
    if previous is None or current is None or previous_kickoff is None:
        return None
    prev_offset = previous_kickoff.astimezone(ZoneInfo(previous[2])).utcoffset()
    curr_offset = current_kickoff.astimezone(ZoneInfo(current[2])).utcoffset()
    if prev_offset is None or curr_offset is None:
        return None
    return int(round((curr_offset - prev_offset).total_seconds() / 3600.0))


def _rest_team_payload(
    *,
    rows: list[dict[str, Any]],
    row: Mapping[str, Any],
    team_id: str,
    side: str,
    game_id: str,
    kickoff: datetime,
    registry: Mapping[str, Any],
    schedule_sha256: str,
) -> dict[str, Any]:
    previous_row, previous_kickoff = _previous_game(
        rows=rows,
        team_id=team_id,
        current_game_id=game_id,
        current_kickoff=kickoff,
    )
    reported_rest = _optional_int(row.get(f"{side}_rest"))
    if reported_rest is None and previous_kickoff is not None:
        reported_rest = (kickoff.date() - previous_kickoff.date()).days
    current_coords = _stadium_coords(row, registry)
    previous_coords = _stadium_coords(previous_row, registry)
    travel_distance = None
    if previous_coords is not None and current_coords is not None:
        travel_distance = haversine_km(
            previous_coords[0],
            previous_coords[1],
            current_coords[0],
            current_coords[1],
        )
    neutral = _neutral_state(row)
    return {
        "team_id": team_id,
        "game_id": game_id,
        "days_rest": reported_rest,
        "short_week": None if reported_rest is None else reported_rest < 7,
        "post_bye": None if reported_rest is None else reported_rest >= 12,
        "consec_road": _road_streak(
            rows=rows,
            team_id=team_id,
            current_game_id=game_id,
            current_kickoff=kickoff,
            current_row=row,
        ),
        "travel_distance_km": travel_distance,
        "tz_shift_hours": _tz_shift_hours(
            previous_coords,
            current_coords,
            previous_kickoff=previous_kickoff,
            current_kickoff=kickoff,
        ),
        "neutral_or_intl": neutral,
        "body_clock_offset": None,
        "previous_game_id": None if previous_row is None else str(previous_row.get("game_id") or "") or None,
        "previous_kickoff_ts": None if previous_kickoff is None else previous_kickoff.isoformat(),
        "kickoff_ts": kickoff.isoformat(),
        "schedule_source_sha256": schedule_sha256,
        "stadium_registry_sha256": str(registry.get("registry_sha256") or ""),
    }


def build_nfl_auto_game_context(
    *,
    game_id: str,
    as_of: Any,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Resolve one NFL game and core objective context without manual prefill.

    The live schedule comes from nflverse. Only schedule/venue/weather-ready
    fields are materialized here. Unsupported or unavailable context stays
    absent so downstream AUTO collection records explicit MISSING states.
    """
    pit = _utc(as_of, "as_of")
    target = str(game_id or "").strip()
    if not target:
        raise NFLContextError("RUN IT game_id required")
    rows, schedule_sha = _fetch_schedule(opener=opener)
    matches = [row for row in rows if str(row.get("game_id") or "").strip() == target]
    if len(matches) != 1:
        raise NFLContextError(f"NFLVERSE game_id resolution failed:{target}:{len(matches)}")
    row = matches[0]
    kickoff = _kickoff(row)
    home = _team(row.get("home_team"))
    away = _team(row.get("away_team"))
    if not home or not away or home == away:
        raise NFLContextError("NFL schedule team identity invalid")

    registry = load_stadium_registry()
    stadium_id = _stadium_id_for_row(row, registry)
    rest_payload = {
        home: _rest_team_payload(
            rows=rows,
            row=row,
            team_id=home,
            side="home",
            game_id=target,
            kickoff=kickoff,
            registry=registry,
            schedule_sha256=schedule_sha,
        ),
        away: _rest_team_payload(
            rows=rows,
            row=row,
            team_id=away,
            side="away",
            game_id=target,
            kickoff=kickoff,
            registry=registry,
            schedule_sha256=schedule_sha,
        ),
    }
    combined_sha = canonical_json_sha256(
        sorted([schedule_sha, str(registry.get("registry_sha256") or "")])
    )
    rest_provider = {
        "status": "AVAILABLE",
        "payload": rest_payload,
        "source_name": "NFLVERSE_SCHEDULE+SPORTSEDGE_STADIUM_REGISTRY",
        "source_uri": NFLVERSE_SCHEDULE_CSV,
        "source_sha256": combined_sha,
        "observed_at": pit,
    }
    return {
        "game_id": target,
        "season": _optional_int(row.get("season")),
        "week": _optional_int(row.get("week")),
        "home_team_id": home,
        "away_team_id": away,
        "kickoff_ts": kickoff.isoformat(),
        "stadium_id": stadium_id,
        "stadium_name": str(row.get("stadium") or "").strip() or None,
        "surface_type": str(row.get("surface") or "").strip() or None,
        "authoritative_roof": _roof_decision(row),
        "location": str(row.get("location") or "").strip() or None,
        "schedule_source_uri": NFLVERSE_SCHEDULE_CSV,
        "schedule_source_sha256": schedule_sha,
        "auto_rest_travel_provider": rest_provider,
    }
