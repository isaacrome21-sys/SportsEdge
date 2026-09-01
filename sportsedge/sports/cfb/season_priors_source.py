from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .context_autopull import CFBContextError
from .source import CFBD_BASE


def _fetch_list(path: str, params: Mapping[str, Any], *, cfbd_api_key: str, opener: Callable = urlopen):
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBContextError("CFBD_API_KEY_REQUIRED")
    query = urlencode({k: v for k, v in params.items() if v is not None})
    uri = f"{CFBD_BASE}{path}?{query}"
    req = Request(uri, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=25) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBContextError(f"CFBD source fetch failed:{path}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBContextError(f"CFBD source JSON invalid:{path}") from exc
    if not isinstance(payload, list):
        raise CFBContextError(f"CFBD source not list:{path}")
    return [dict(row) for row in payload if isinstance(row, Mapping)], uri, sha256(raw).hexdigest()


def fetch_returning_production(*, season: int, cfbd_api_key: str, opener: Callable = urlopen):
    rows, uri, digest = _fetch_list("/player/returning", {"year": int(season)}, cfbd_api_key=cfbd_api_key, opener=opener)
    by_team: dict[str, dict[str, Any]] = {}
    for row in rows:
        team = str(row.get("team") or "").strip()
        if not team:
            continue
        by_team[team] = {
            "season": int(row.get("season", season)),
            "team": team,
            "conference": row.get("conference"),
            "total_ppa": row.get("totalPPA"),
            "total_passing_ppa": row.get("totalPassingPPA"),
            "total_receiving_ppa": row.get("totalReceivingPPA"),
            "total_rushing_ppa": row.get("totalRushingPPA"),
            "percent_ppa": row.get("percentPPA"),
            "percent_passing_ppa": row.get("percentPassingPPA"),
            "percent_receiving_ppa": row.get("percentReceivingPPA"),
            "percent_rushing_ppa": row.get("percentRushingPPA"),
            "usage": row.get("usage"),
            "passing_usage": row.get("passingUsage"),
            "receiving_usage": row.get("receivingUsage"),
            "rushing_usage": row.get("rushingUsage"),
        }
    return by_team, uri, digest


def fetch_team_talent(*, season: int, cfbd_api_key: str, opener: Callable = urlopen):
    rows, uri, digest = _fetch_list("/talent", {"year": int(season)}, cfbd_api_key=cfbd_api_key, opener=opener)
    by_team: dict[str, dict[str, Any]] = {}
    for row in rows:
        team = str(row.get("school") or row.get("team") or "").strip()
        if not team:
            continue
        talent = row.get("talent")
        if talent is None:
            continue
        by_team[team] = {"season": int(row.get("year", season)), "team": team, "talent": float(talent)}
    return by_team, uri, digest


def fetch_prior_season_player_usage(*, season: int, cfbd_api_key: str, opener: Callable = urlopen):
    prior = int(season) - 1
    rows, uri, digest = _fetch_list(
        "/player/usage", {"year": prior, "excludeGarbageTime": "true"},
        cfbd_api_key=cfbd_api_key, opener=opener,
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        athlete_id = str(row.get("id") or row.get("athleteId") or "").strip()
        if not athlete_id:
            continue
        usage = row.get("usage") if isinstance(row.get("usage"), Mapping) else {}
        normalized.append({
            "season": int(row.get("season", prior)),
            "athlete_id": athlete_id,
            "name": str(row.get("name") or "").strip() or None,
            "previous_team": str(row.get("team") or "").strip() or None,
            "position": str(row.get("position") or "").strip() or None,
            "conference": row.get("conference"),
            "usage_overall": usage.get("overall"),
            "usage_pass": usage.get("pass"),
            "usage_rush": usage.get("rush"),
            "usage_first_down": usage.get("firstDown"),
            "usage_second_down": usage.get("secondDown"),
            "usage_third_down": usage.get("thirdDown"),
            "usage_standard_downs": usage.get("standardDowns"),
            "usage_passing_downs": usage.get("passingDowns"),
            "baseline_only": True,
        })
    return normalized, uri, digest


def match_usage_to_current_roster(
    *, usage_rows: Iterable[Mapping[str, Any]], current_roster_rows: Iterable[Mapping[str, Any]], current_team: str,
) -> list[dict[str, Any]]:
    current_ids = {str(row.get("athlete_id") or "").strip(): dict(row) for row in current_roster_rows if str(row.get("athlete_id") or "").strip()}
    out: list[dict[str, Any]] = []
    for raw in usage_rows:
        athlete_id = str(raw.get("athlete_id") or "").strip()
        current = current_ids.get(athlete_id)
        if current is None:
            continue
        row = dict(raw)
        row["current_team"] = str(current_team)
        row["current_position"] = current.get("position")
        row["transfer_team_changed"] = bool(row.get("previous_team") and str(row.get("previous_team")) != str(current_team))
        out.append(row)
    out.sort(key=lambda row: (str(row.get("current_position") or ""), str(row.get("athlete_id") or "")))
    return out
