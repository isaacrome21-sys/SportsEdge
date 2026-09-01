from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from ...source_lineage import canonical_json_sha256
from .auto_objective_sources import build_cfbd_provider_factory, _fetch_fbs_schedule, _rest_payload, _utc
from .travel_source import fetch_cfbd_fbs_venue_registry, enrich_rest_travel_payload


def build_cfbd_enriched_provider_factory(*, cfbd_api_key: str, opener: Callable = urlopen) -> Callable:
    """Extend canonical CFBD providers with coordinate-derived rest/travel context."""
    base_factory = build_cfbd_provider_factory(cfbd_api_key=cfbd_api_key, opener=opener)
    schedule_cache: dict[int, tuple[list[dict[str, Any]], str, str]] = {}
    venue_cache: dict[int, tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str, str]] = {}

    def factory(game: Mapping[str, Any], pit: datetime) -> Mapping[str, Callable]:
        providers = dict(base_factory(game, pit))
        season = int(game["season"])
        game_id = str(game["game_id"])
        home = str(game["home_team"])
        away = str(game["away_team"])

        def rest_travel(requested_game_id: str, as_of: datetime):
            if season not in schedule_cache:
                schedule_cache[season] = _fetch_fbs_schedule(
                    season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            if season not in venue_cache:
                venue_cache[season] = fetch_cfbd_fbs_venue_registry(
                    season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            schedule_rows, schedule_sha, schedule_uri = schedule_cache[season]
            by_team, by_venue, venue_sha, venue_uri = venue_cache[season]
            current_kickoff = _utc(game.get("kickoff_ts"), "kickoff_ts")

            def one(team: str):
                row = _rest_payload(team=team, rows=schedule_rows, game=game, as_of=as_of)
                if row is None:
                    return None
                previous_id = str(row.get("previous_game_id") or "")
                previous_game = None
                for raw in schedule_rows:
                    if str(raw.get("id") or "") == previous_id:
                        previous_game = {
                            "home": raw.get("homeTeam"),
                            "away": raw.get("awayTeam"),
                            "neutral": bool(raw.get("neutralSite", False)),
                            "venue_id": raw.get("venueId"),
                        }
                        break
                if previous_game is None:
                    return row
                return enrich_rest_travel_payload(
                    payload=row,
                    current_game=game,
                    previous_game=previous_game,
                    current_kickoff=current_kickoff,
                    by_team=by_team,
                    by_venue=by_venue,
                )

            home_row, away_row = one(home), one(away)
            if home_row is None and away_row is None:
                return None
            payload = {
                "game_id": game_id,
                "home": home_row,
                "away": away_row,
                "neutral_site": bool(game.get("neutral_site", False)),
                "venue_registry_source_uri": venue_uri,
            }
            return {
                "status": "AVAILABLE",
                "payload": payload,
                "source_name": "CFBD_FBS_SCHEDULE+FBS_VENUE_REGISTRY_PRIOR_ONLY",
                "source_uri": schedule_uri,
                "source_sha256": canonical_json_sha256([schedule_sha, venue_sha, payload]),
                "observed_at": as_of,
            }

        providers["rest_travel"] = rest_travel
        return providers

    return factory
