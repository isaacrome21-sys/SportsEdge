from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...source_lineage import canonical_json_sha256
from .context_autopull import CFBContextError
from .source import CFBD_BASE, fetch_cfbd_team_metrics, fetch_cfbd_weather


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBContextError(f"{field} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _fetch_fbs_schedule(*, season: int, cfbd_api_key: str, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBContextError("CFBD_API_KEY_REQUIRED")
    query = urlencode({"year": int(season), "seasonType": "regular", "classification": "fbs"})
    uri = f"{CFBD_BASE}/games?{query}"
    req = Request(uri, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBContextError("CFBD FBS schedule fetch failed") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBContextError("CFBD FBS schedule JSON invalid") from exc
    if not isinstance(payload, list):
        raise CFBContextError("CFBD FBS schedule not list")
    return [dict(row) for row in payload if isinstance(row, Mapping)], sha256(raw).hexdigest(), uri


def _team_history(*, rows: list[dict[str, Any]], team: str, current_game_id: str,
                  current_kickoff: datetime, as_of: datetime) -> list[dict[str, Any]]:
    cutoff = min(current_kickoff, as_of)
    history: list[dict[str, Any]] = []
    for row in rows:
        game_id = str(row.get("id") or "").strip()
        if not game_id or game_id == current_game_id:
            continue
        home = str(row.get("homeTeam") or "").strip()
        away = str(row.get("awayTeam") or "").strip()
        if team not in {home, away}:
            continue
        try:
            kickoff = _utc(row.get("startDate"), "startDate")
        except CFBContextError:
            continue
        if kickoff >= cutoff:
            continue
        history.append({
            "game_id": game_id,
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "neutral": bool(row.get("neutralSite", False)),
            "venue": str(row.get("venue") or "").strip() or None,
            "venue_id": row.get("venueId"),
        })
    history.sort(key=lambda item: (item["kickoff"], item["game_id"]))
    return history


def _rest_payload(*, team: str, rows: list[dict[str, Any]], game: Mapping[str, Any], as_of: datetime) -> dict[str, Any] | None:
    current_kickoff = _utc(game.get("kickoff_ts"), "kickoff_ts")
    history = _team_history(
        rows=rows,
        team=team,
        current_game_id=str(game.get("game_id") or ""),
        current_kickoff=current_kickoff,
        as_of=as_of,
    )
    if not history:
        return None
    previous = history[-1]
    rest_hours = (current_kickoff - previous["kickoff"]).total_seconds() / 3600.0
    road_streak = 0
    for prior in reversed(history):
        if prior["neutral"] or prior["home"] == team:
            break
        if prior["away"] == team:
            road_streak += 1
        else:
            break
    return {
        "team": team,
        "previous_game_id": previous["game_id"],
        "previous_kickoff_utc": previous["kickoff"].isoformat(),
        "rest_hours_to_current_kickoff": round(rest_hours, 3),
        "days_rest_floor": int(rest_hours // 24),
        "short_week": rest_hours < 7 * 24,
        "post_bye": rest_hours >= 12 * 24,
        "consecutive_road_games_entering": road_streak,
        "previous_venue": previous["venue"],
        "previous_venue_id": previous["venue_id"],
        "travel_distance_km": None,
        "timezone_shift_hours": None,
        "travel_status": "UNAVAILABLE_NO_COORDINATE_SOURCE",
    }


def build_cfbd_provider_factory(*, cfbd_api_key: str, opener: Callable = urlopen) -> Callable:
    """Return a per-game provider factory backed only by objective CFBD data."""
    weather_cache: dict[tuple[int, int], Mapping[str, Mapping[str, Any]]] = {}
    metric_cache: dict[tuple[int, int, str], Mapping[str, Any]] = {}
    schedule_cache: dict[int, tuple[list[dict[str, Any]], str, str]] = {}

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

        def _metrics(as_of: datetime) -> Mapping[str, Any]:
            cache_key = (season, week, as_of.isoformat())
            if cache_key not in metric_cache:
                metric_cache[cache_key] = fetch_cfbd_team_metrics(
                    season=season, week=week, cfbd_api_key=cfbd_api_key,
                    now=as_of, opener=opener)
            return metric_cache[cache_key]

        def rest_provider(requested_game_id: str, as_of: datetime):
            if season not in schedule_cache:
                schedule_cache[season] = _fetch_fbs_schedule(
                    season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            rows, schedule_sha, schedule_uri = schedule_cache[season]
            home_row = _rest_payload(team=home, rows=rows, game=game, as_of=as_of)
            away_row = _rest_payload(team=away, rows=rows, game=game, as_of=as_of)
            if home_row is None and away_row is None:
                return None
            payload = {
                "game_id": game_id,
                "home": home_row,
                "away": away_row,
                "neutral_site": bool(game.get("neutral_site", False)),
            }
            return {
                "status": "AVAILABLE",
                "payload": payload,
                "source_name": "CFBD_FBS_SCHEDULE_PRIOR_ONLY",
                "source_uri": schedule_uri,
                "source_sha256": canonical_json_sha256([schedule_sha, payload]),
                "observed_at": as_of,
            }

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
            "rest_travel": rest_provider,
            "team_efficiency_pace": efficiency_provider,
            "defensive_matchup": defensive_provider,
        }

    return factory
