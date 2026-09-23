"""MLB roster / IL / scratch acquisition from public StatsAPI only."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .source_lineage import canonical_json_sha256

MLB_STATSAPI = "https://statsapi.mlb.com/api/v1"
SOURCE = "MLB_STATSAPI_ROSTER_TRANSACTIONS"
SCHEMA_VERSION = "mlb_injury_scratch_source_v2"
MEANINGFUL_TYPES = {
    "IL", "SCK", "SC", "DES", "OPT", "REC", "ASG", "SE", "OUT", "REL", "RET", "CLW",
}
INJURY_TOKENS = (
    "injured list", "10-day", "15-day", "60-day", "il ", " placed on",
    "transferred", "activated", "scratched", "bereavement", "paternity",
)


class MLBInjuryScratchError(RuntimeError):
    pass


def _open_json(url: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-MLB-Roster/1.0",
    })
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBInjuryScratchError(f"ROSTER_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBInjuryScratchError("ROSTER_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise MLBInjuryScratchError("ROSTER_RESPONSE_NOT_OBJECT")
    return payload


def roster_url(team_id: int) -> str:
    return f"{MLB_STATSAPI}/teams/{int(team_id)}/roster?" + urlencode({"rosterType": "40Man"})


def transactions_url(*, team_id: int, start: str, end: str) -> str:
    return f"{MLB_STATSAPI}/transactions?" + urlencode({
        "teamId": int(team_id),
        "startDate": start,
        "endDate": end,
    })


def _team_ids(live_payload: Mapping[str, Any]) -> dict[str, int | None]:
    teams = ((live_payload.get("gameData") or {}).get("teams") or {})
    out: dict[str, int | None] = {"away": None, "home": None}
    for side in ("away", "home"):
        try:
            out[side] = int((teams.get(side) or {}).get("id"))
        except (TypeError, ValueError):
            out[side] = None
    return out


def parse_roster(payload: Mapping[str, Any], *, team_id: int) -> list[dict[str, Any]]:
    rows = []
    for item in payload.get("roster") or []:
        if not isinstance(item, Mapping):
            continue
        person = item.get("person") or {}
        status = item.get("status") or {}
        position = item.get("position") or {}
        try:
            pid = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        rows.append({
            "team_id": int(team_id),
            "player_id": pid,
            "player_name": str(person.get("fullName") or "").strip() or None,
            "jersey_number": str(item.get("jerseyNumber") or "").strip() or None,
            "position": str(position.get("abbreviation") or "").strip() or None,
            "status_code": str(status.get("code") or "").strip() or None,
            "status": str(status.get("description") or "").strip() or None,
        })
    return rows


def parse_transactions(payload: Mapping[str, Any], *, team_id: int) -> list[dict[str, Any]]:
    rows = []
    for item in payload.get("transactions") or []:
        if not isinstance(item, Mapping):
            continue
        type_code = str(item.get("typeCode") or "").upper()
        description = str(item.get("description") or "")
        lowered = description.lower()
        meaningful = type_code in MEANINGFUL_TYPES or any(token in lowered for token in INJURY_TOKENS)
        if not meaningful:
            continue
        person = item.get("person") or {}
        try:
            pid = int(person.get("id")) if person.get("id") is not None else None
        except (TypeError, ValueError):
            pid = None
        rows.append({
            "team_id": int(team_id),
            "player_id": pid,
            "player_name": str(person.get("fullName") or "").strip() or None,
            "date": item.get("date") or item.get("effectiveDate"),
            "type_code": type_code,
            "type_desc": item.get("typeDesc"),
            "description": description,
            "injury_like": any(token in lowered for token in INJURY_TOKENS),
        })
    return rows


def confirmed_lineup_ids(live_payload: Mapping[str, Any]) -> dict[str, list[int]]:
    teams = ((live_payload.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    out: dict[str, list[int]] = {"away": [], "home": []}
    if not isinstance(teams, Mapping):
        return out
    for side in ("away", "home"):
        ids = []
        for raw in (teams.get(side) or {}).get("battingOrder") or []:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        out[side] = ids
    return out


def _normalized_lineup_ids(value: Mapping[str, Any] | None) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {"away": [], "home": []}
    if not isinstance(value, Mapping):
        return out
    for side in ("away", "home"):
        for raw in value.get(side) or []:
            try:
                out[side].append(int(raw))
            except (TypeError, ValueError):
                continue
    return out


def lineup_change_evidence(
    *,
    current: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
    rosters: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    current_ids = _normalized_lineup_ids(current)
    baseline_ids = _normalized_lineup_ids(baseline)
    rosters = rosters or {}
    sides: dict[str, dict[str, Any]] = {}
    removed_rows: list[dict[str, Any]] = []

    for side in ("away", "home"):
        before = baseline_ids[side]
        after = current_ids[side]
        if baseline is None or not before:
            status = "BASELINE_UNAVAILABLE"
            removed: list[int] = []
            added: list[int] = []
        elif not after:
            status = "CURRENT_LINEUP_UNAVAILABLE"
            removed = []
            added = []
        else:
            status = "EVALUABLE"
            removed = sorted(set(before) - set(after))
            added = sorted(set(after) - set(before))

        roster_index = {
            int(row["player_id"]): row
            for row in rosters.get(side, [])
            if isinstance(row, Mapping) and row.get("player_id") is not None
        }
        for player_id in removed:
            roster_row = roster_index.get(player_id) or {}
            removed_rows.append({
                "side": side,
                "player_id": player_id,
                "player_name": roster_row.get("player_name"),
                "evidence": "POSTED_LINEUP_REMOVAL",
            })
        sides[side] = {
            "status": status,
            "baseline_lineup_ids": before,
            "current_lineup_ids": after,
            "removed_player_ids": removed,
            "added_player_ids": added,
        }

    evaluable = any(row["status"] == "EVALUABLE" for row in sides.values())
    return {
        "evaluable": evaluable,
        "sides": sides,
        "removed_players": removed_rows,
    }


def acquire_injuries_and_scratches(
    *,
    game_pk: int,
    as_of: datetime,
    live_payload: Mapping[str, Any] | None = None,
    opener: Callable = urlopen,
    lookback_days: int = 7,
    baseline_lineup_ids: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    live_payload = live_payload or {}
    teams = _team_ids(live_payload)
    start = (as_of.date() - timedelta(days=int(lookback_days))).isoformat()
    end = as_of.date().isoformat()
    rosters: dict[str, list[dict[str, Any]]] = {}
    transactions: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for side, team_id in teams.items():
        if team_id is None:
            rosters[side] = []
            transactions[side] = []
            errors.append(f"MISSING_TEAM_ID_{side.upper()}")
            continue
        try:
            rosters[side] = parse_roster(_open_json(roster_url(team_id), opener=opener), team_id=team_id)
        except MLBInjuryScratchError as exc:
            rosters[side] = []
            errors.append(f"{side}: {exc}")
        try:
            transactions[side] = parse_transactions(
                _open_json(transactions_url(team_id=team_id, start=start, end=end), opener=opener),
                team_id=team_id,
            )
        except MLBInjuryScratchError as exc:
            transactions[side] = []
            errors.append(f"{side}: {exc}")

    lineup = confirmed_lineup_ids(live_payload)
    explicit_scratches = [
        row
        for side_rows in transactions.values()
        for row in side_rows
        if "scratch" in str(row.get("description") or "").lower()
    ]
    lineup_changes = lineup_change_evidence(
        current=lineup,
        baseline=baseline_lineup_ids,
        rosters=rosters,
    )
    if explicit_scratches or lineup_changes["removed_players"]:
        scratch_detection_status = "EVIDENCE_PRESENT"
    elif lineup_changes["evaluable"]:
        scratch_detection_status = "EVALUATED_NO_EVIDENCE"
    else:
        scratch_detection_status = "NOT_EVALUABLE"

    il_rows = [
        row
        for side_rows in transactions.values()
        for row in side_rows
        if row.get("injury_like")
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.isoformat(),
        "source": SOURCE,
        "lookback_days": int(lookback_days),
        "teams": teams,
        "rosters": {side: {"count": len(rows), "players": rows} for side, rows in rosters.items()},
        "transactions": transactions,
        "injury_like_moves": il_rows,
        "confirmed_lineup_ids": lineup,
        "explicit_scratches": explicit_scratches,
        "lineup_change_evidence": lineup_changes,
        "scratch_detection_status": scratch_detection_status,
        "errors": errors,
        "status": "AVAILABLE" if any(rosters.values()) or any(transactions.values()) or any(lineup.values()) else "MISSING",
        "model_p_eligible": False,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
