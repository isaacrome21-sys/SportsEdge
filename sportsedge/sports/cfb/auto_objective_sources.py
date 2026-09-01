from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from ...source_lineage import canonical_json_sha256
from .context_autopull import CFBContextError
from .source import CFBD_BASE, fetch_cfbd_team_metrics, fetch_cfbd_weather


def build_cfbd_provider_factory(*, cfbd_api_key: str, opener: Callable = urlopen) -> Callable:
    """Return a per-game provider factory backed only by objective CFBD data.

    Weather and prior-week/prior-season team efficiency are fetched lazily and
    cached by season/week. No odds, public-betting, social, or market fields are
    requested or admitted into the context lane.
    """
    weather_cache: dict[tuple[int, int], Mapping[str, Mapping[str, Any]]] = {}
    metric_cache: dict[tuple[int, int, str], Mapping[str, Any]] = {}

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
            "team_efficiency_pace": efficiency_provider,
            "defensive_matchup": defensive_provider,
        }

    return factory
