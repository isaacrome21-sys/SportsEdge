"""Full pregame context snapshot for SportsEdge MLB.

Weather, roof, plate umpire, catcher identity/metrics, starters and lineup basis
are captured with exact game identity.  V5 consumption flags are explicit:
Statcast and lineup identity are model-driving; weather/umpire/catcher are not
silently injected into the already-attested V5 artifact.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .catcher_context import build_catcher_context, catcher_from_confirmed_box
from .mlb_context import fetch_slate_context
from .mlb_source import BASE, MLBSourceError, _get_json, fetch_boxscore


def _active_catcher_ids(team_id: int) -> set[int]:
    payload = _get_json(f"{BASE}/api/v1/teams/{int(team_id)}/roster?rosterType=active")
    out: set[int] = set()
    for row in payload.get("roster") or []:
        position = row.get("position") or {}
        if str(position.get("abbreviation") or "").upper() != "C":
            continue
        person = row.get("person") or {}
        try:
            pid = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        if pid > 0:
            out.add(pid)
    return out


def _projected_catcher(lineup_ids: tuple[int, ...], team_id: int) -> int:
    active = _active_catcher_ids(team_id)
    found = [pid for pid in lineup_ids if int(pid) in active]
    if len(found) != 1:
        raise MLBSourceError("PROJECTED_STARTING_CATCHER_UNRESOLVED")
    return int(found[0])


def build_full_pregame_context(*, schedule, resolved_lineups: Mapping[tuple[str, str], Any], catcher_boards: Mapping[str, list[dict[str, Any]]], now: datetime) -> dict[str, dict[str, Any]]:
    base = {str(row.game_id): row for row in fetch_slate_context(list(schedule))}
    output: dict[str, dict[str, Any]] = {}
    for game in schedule:
        gid = str(game.game_pk)
        row = base.get(gid)
        item: dict[str, Any] = {
            "game_id": gid,
            "retrieved_at_utc": now.isoformat(),
            "weather": None if row is None else row.weather,
            "weather_status": "MISSING" if row is None else row.weather_status,
            "roof_type": None if row is None else row.roof_type,
            "venue_name": None if row is None else row.venue_name,
            "plate_umpire": None if row is None else row.plate_umpire,
            "plate_umpire_status": "MISSING" if row is None else row.plate_umpire_status,
            "away_catcher": None,
            "home_catcher": None,
            "model_p_consumption": {
                "statcast": True,
                "lineup_identity": True,
                "weather": False,
                "plate_umpire": False,
                "catcher": False,
            },
        }
        try:
            box = fetch_boxscore(game.game_pk)
            for side, team_id in (("away", game.away_id), ("home", game.home_id)):
                lineup = resolved_lineups.get((gid, side))
                if lineup is None:
                    raise MLBSourceError(f"CONTEXT_LINEUP_MISSING:{side}")
                try:
                    pid, name = catcher_from_confirmed_box(box, side)
                    basis = "CONFIRMED_MLB"
                except Exception:
                    pid = _projected_catcher(tuple(int(x) for x in lineup.player_ids), int(team_id))
                    name = None
                    basis = str(lineup.basis)
                item[f"{side}_catcher"] = build_catcher_context(pid, name, basis, catcher_boards)
        except Exception as exc:
            item["catcher_status"] = f"BLOCKED:{type(exc).__name__}:{exc}"
        else:
            item["catcher_status"] = "RESOLVED"
        output[gid] = item
    return output
