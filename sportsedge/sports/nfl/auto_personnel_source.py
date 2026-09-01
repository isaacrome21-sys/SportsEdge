from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .context_autopull import NFLContextError
from .personnel_coaching_context import build_personnel_provider

_TEAM_ALIASES = {"LA": "LAR", "WSH": "WAS"}
_OL_ABB = frozenset({"C", "G", "LG", "RG", "T", "LT", "RT", "OL"})
_SECONDARY_ABB = frozenset({"CB", "DB", "FS", "SS", "S", "NB"})


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return _TEAM_ALIASES.get(raw, raw)


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


def _rank_one(value: Any) -> bool:
    try:
        return int(float(value)) == 1
    except (TypeError, ValueError):
        return False


def _slot(row: Mapping[str, Any]) -> str:
    raw = row.get("pos_slot")
    if raw not in (None, ""):
        return f"slot:{raw}"
    pos = str(row.get("pos_abb") or row.get("pos_name") or "").strip().upper()
    return f"pos:{pos}" if pos else ""


def _starter_slot_count(rows: Iterable[Mapping[str, Any]], allowed: frozenset[str]) -> int:
    slots: set[str] = set()
    for row in rows:
        if not _rank_one(row.get("pos_rank")):
            continue
        pos = str(row.get("pos_abb") or "").strip().upper()
        if pos not in allowed:
            continue
        player_id = str(row.get("gsis_id") or row.get("espn_id") or "").strip()
        slot = _slot(row)
        if player_id and slot:
            slots.add(slot)
    return len(slots)


def _latest_team_snapshot(
    *,
    rows: Iterable[Mapping[str, Any]],
    team_id: str,
    as_of: datetime,
) -> tuple[datetime | None, list[dict[str, Any]]]:
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        if _team(row.get("team") or row.get("club_code")) != team_id:
            continue
        if row.get("dt") in (None, ""):
            continue
        stamp = _utc(row.get("dt"), "depth dt")
        if stamp <= as_of:
            eligible.append((stamp, row))
    if not eligible:
        return None, []
    latest = max(stamp for stamp, _ in eligible)
    snapshot = [row for stamp, row in eligible if stamp == latest]
    return latest, snapshot


def build_depth_chart_personnel_provider(
    *,
    game_id: str,
    team_ids: Iterable[str],
    as_of: Any,
    source_uri: str,
    source_sha256: str,
    rows: Iterable[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Derive only depth-chart facts that a PIT snapshot can support honestly.

    This intentionally does not synthesize 11/12/13 personnel, nickel/dime, or
    OL continuity rates from depth-chart ordering. Those fields remain None.
    """
    pit = _utc(as_of, "as_of")
    materialized = [dict(row) for row in rows]
    targets = tuple(dict.fromkeys(_team(team) for team in team_ids if _team(team)))
    if not targets:
        raise NFLContextError("depth personnel team_ids required")
    source = str(source_uri or "").strip()
    if not source.startswith("https://"):
        raise NFLContextError("depth personnel source_uri must be https")
    digest = str(source_sha256 or "").strip().lower()
    if len(digest) != 64:
        raise NFLContextError("depth personnel source_sha256 invalid")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise NFLContextError("depth personnel source_sha256 invalid") from exc

    provider_rows: list[dict[str, Any]] = []
    snapshot_times: dict[str, str] = {}
    missing_team_ids: list[str] = []
    for team_id in targets:
        stamp, snapshot = _latest_team_snapshot(rows=materialized, team_id=team_id, as_of=pit)
        if stamp is None or not snapshot:
            missing_team_ids.append(team_id)
            continue
        snapshot_times[team_id] = stamp.isoformat()
        provider_rows.append(
            {
                "team_id": team_id,
                "eleven_personnel_rate": None,
                "twelve_personnel_rate": None,
                "thirteen_personnel_rate": None,
                "empty_rate": None,
                "nickel_rate": None,
                "dime_rate": None,
                "ol_continuity_starts": None,
                "projected_ol_starters_known": _starter_slot_count(snapshot, _OL_ABB) >= 5,
                "starting_secondary_known": _starter_slot_count(snapshot, _SECONDARY_ABB) >= 4,
            }
        )
    if not provider_rows:
        return None
    row = dict(
        build_personnel_provider(
            game_id=str(game_id),
            as_of=pit,
            source_uri=source,
            source_sha256=digest,
            rows=provider_rows,
        )
    )
    payload = dict(row.get("payload") or {})
    payload["depth_snapshot_asof_by_team"] = snapshot_times
    payload["missing_team_ids"] = missing_team_ids
    payload["derived_fields"] = [
        "projected_ol_starters_known",
        "starting_secondary_known",
    ]
    payload["intentionally_unresolved_fields"] = [
        "eleven_personnel_rate",
        "twelve_personnel_rate",
        "thirteen_personnel_rate",
        "empty_rate",
        "nickel_rate",
        "dime_rate",
        "ol_continuity_starts",
    ]
    row["payload"] = payload
    row["status"] = "PARTIAL" if missing_team_ids else "AVAILABLE"
    row["source_name"] = "PIT_NFLVERSE_DEPTH_CHARTS"
    return row
