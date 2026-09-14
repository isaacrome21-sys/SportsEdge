from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...source_lineage import canonical_json_sha256
from .context_autopull import CFBContextError
from .source import CFBD_BASE, fetch_cfbd_team_metrics, fetch_cfbd_weather


def _fetch_fbs_roster_snapshot(*, season: int, cfbd_api_key: str, opener: Callable = urlopen):
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBContextError("CFBD_API_KEY_REQUIRED")
    uri = f"{CFBD_BASE}/roster?" + urlencode({"year": int(season), "classification": "fbs"})
    req = Request(uri, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=25) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBContextError("CFBD roster fetch failed") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBContextError("CFBD roster JSON invalid") from exc
    if not isinstance(payload, list):
        raise CFBContextError("CFBD roster payload not list")
    by_team: dict[str, list[dict[str, Any]]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        team = str(row.get("team") or "").strip()
        athlete_id = str(row.get("id") or row.get("athleteId") or row.get("athlete_id") or "").strip()
        first = str(row.get("firstName") or row.get("first_name") or "").strip()
        last = str(row.get("lastName") or row.get("last_name") or "").strip()
        position = str(row.get("position") or "").strip()
        if not team or not athlete_id or not (first or last):
            continue
        normalized = {
            "athlete_id": athlete_id,
            "first_name": first or None,
            "last_name": last or None,
            "full_name": " ".join(part for part in (first, last) if part) or None,
            "team": team,
            "position": position or None,
            "jersey": row.get("jersey"),
            "year": row.get("year"),
            "height": row.get("height"),
            "weight": row.get("weight"),
        }
        by_team.setdefault(team, []).append(normalized)
    if not by_team:
        raise CFBContextError("CFBD FBS roster snapshot empty")
    for rows in by_team.values():
        rows.sort(key=lambda item: (str(item.get("position") or ""), str(item.get("athlete_id") or "")))
    return by_team, uri, sha256(raw).hexdigest()


def build_cfbd_provider_factory(*, cfbd_api_key: str, opener: Callable = urlopen) -> Callable:
    """Return a per-game provider factory backed only by objective CFBD data."""
    weather_cache: dict[tuple[int, int], Mapping[str, Mapping[str, Any]]] = {}
    metric_cache: dict[tuple[int, int, str], Mapping[str, Any]] = {}
    roster_cache: dict[int, tuple[dict[str, list[dict[str, Any]]], str, str]] = {}

    def factory(game: Mapping[str, Any], pit: datetime) -> Mapping[str, Callable]:
        season = int(game["season"])
        week = int(game["week"])
        game_id = str(game["game_id"])
        home = str(game["home_team"])
        away = str(game["away_team"])

        def weather_provider(requested_game_id: str, as_of: datetime):
            key = (season, week)
            if key not in weather_cache:
                weather_cache[key] = fetch_cfbd_weather(
                    season=season, week=week, cfbd_api_key=cfbd_api_key, opener=opener)
            weather = weather_cache[key].get(game_id)
            if weather is None:
                return None
            payload = {
                "game_id": game_id,
                "venue": game.get("venue"),
                "venue_id": game.get("venue_id"),
                "weather": dict(weather),
            }
            return {
                "status": "AVAILABLE", "payload": payload,
                "source_name": "CFBD_GAMES_WEATHER",
                "source_uri": f"{CFBD_BASE}/games/weather",
                "source_sha256": canonical_json_sha256(payload),
                "observed_at": as_of,
            }

        def roster_identity_provider(requested_game_id: str, as_of: datetime):
            if season not in roster_cache:
                roster_cache[season] = _fetch_fbs_roster_snapshot(
                    season=season, cfbd_api_key=cfbd_api_key, opener=opener
                )
            rosters, uri, digest = roster_cache[season]
            home_rows = list(rosters.get(home) or [])
            away_rows = list(rosters.get(away) or [])
            if not home_rows or not away_rows:
                return None
            payload = {
                "game_id": game_id,
                "home_team": home,
                "away_team": away,
                "home_roster": home_rows,
                "away_roster": away_rows,
                "identity_namespace": "CFBD_ATHLETE_ID",
                "depth_chart_confirmed": False,
                "role_order_confirmed": False,
                "freshness_note": "SEASON_ROSTER_HAS_NO_ROW_LEVEL_MODIFIED_TIMESTAMP",
            }
            return {
                # Roster identity is useful automatically, but it is deliberately
                # not declared AVAILABLE depth-chart role evidence.
                "status": "PARTIAL_ROSTER_IDENTITY_ONLY",
                "payload": payload,
                "source_name": "CFBD_FBS_ROSTER_IDENTITY",
                "source_uri": uri,
                "source_sha256": digest,
                "observed_at": as_of,
            }

        def _metrics(as_of: datetime) -> Mapping[str, Any]:
            cache_key = (season, week, as_of.isoformat())
            if cache_key not in metric_cache:
                metric_cache[cache_key] = fetch_cfbd_team_metrics(
                    season=season, week=week, cfbd_api_key=cfbd_api_key,
                    now=as_of, opener=opener)
            return metric_cache[cache_key]

        def efficiency_provider(requested_game_id: str, as_of: datetime):
            metrics = _metrics(as_of)
            home_row, away_row = metrics.get(home), metrics.get(away)
            if home_row is None or away_row is None:
                return None
            payload = {"game_id": game_id, "home": home_row.to_dict(), "away": away_row.to_dict()}
            return {
                "status": "AVAILABLE", "payload": payload,
                "source_name": "CFBD_ADVANCED_TEAM_METRICS_PRIOR_ONLY",
                "source_uri": f"{CFBD_BASE}/stats/season/advanced",
                "source_sha256": canonical_json_sha256(payload), "observed_at": as_of,
            }

        def defensive_provider(requested_game_id: str, as_of: datetime):
            metrics = _metrics(as_of)
            home_row, away_row = metrics.get(home), metrics.get(away)
            if home_row is None or away_row is None:
                return None
            payload = {
                "game_id": game_id,
                "home_offense_vs_away_defense": {
                    "off_ppa_rush": home_row.off_ppa_rush,
                    "off_ppa_dropback": home_row.off_ppa_dropback,
                    "off_success_rate": home_row.off_success_rate,
                    "opponent_def_ppa_rush_allowed": away_row.def_ppa_rush_allowed,
                    "opponent_def_ppa_dropback_allowed": away_row.def_ppa_dropback_allowed,
                    "opponent_def_success_rate_allowed": away_row.def_success_rate_allowed,
                },
                "away_offense_vs_home_defense": {
                    "off_ppa_rush": away_row.off_ppa_rush,
                    "off_ppa_dropback": away_row.off_ppa_dropback,
                    "off_success_rate": away_row.off_success_rate,
                    "opponent_def_ppa_rush_allowed": home_row.def_ppa_rush_allowed,
                    "opponent_def_ppa_dropback_allowed": home_row.def_ppa_dropback_allowed,
                    "opponent_def_success_rate_allowed": home_row.def_success_rate_allowed,
                },
                "sample_source": home_row.sample_source,
                "through_week": home_row.through_week,
            }
            return {
                "status": "AVAILABLE", "payload": payload,
                "source_name": "CFBD_ADVANCED_MATCHUP_PRIOR_ONLY",
                "source_uri": f"{CFBD_BASE}/stats/season/advanced",
                "source_sha256": canonical_json_sha256(payload), "observed_at": as_of,
            }

        return {
            "venue_weather": weather_provider,
            "depth_chart_role": roster_identity_provider,
            "team_efficiency_pace": efficiency_provider,
            "defensive_matchup": defensive_provider,
        }

    return factory
