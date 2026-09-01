from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping
from urllib.request import urlopen

from ...source_lineage import canonical_json_sha256
from .auto_objective_sources import build_cfbd_provider_factory, _fetch_fbs_roster_snapshot
from .season_priors_source import (
    fetch_returning_production,
    fetch_team_talent,
    fetch_prior_season_player_usage,
    match_usage_to_current_roster,
)


def build_cfbd_season_priors_provider_factory(*, cfbd_api_key: str, opener: Callable = urlopen) -> Callable:
    """Extend canonical CFBD objective context with pregame season priors.

    Returning production and talent are live season priors. Prior-season player usage
    is only a baseline and deliberately does not satisfy current workload/depth-chart
    completeness by itself.
    """
    base_factory = build_cfbd_provider_factory(cfbd_api_key=cfbd_api_key, opener=opener)
    returning_cache: dict[int, tuple[dict[str, dict[str, Any]], str, str]] = {}
    talent_cache: dict[int, tuple[dict[str, dict[str, Any]], str, str]] = {}
    usage_cache: dict[int, tuple[list[dict[str, Any]], str, str]] = {}
    roster_cache: dict[int, tuple[dict[str, list[dict[str, Any]]], str, str]] = {}

    def factory(game: Mapping[str, Any], pit: datetime) -> Mapping[str, Callable]:
        providers = dict(base_factory(game, pit))
        season = int(game["season"])
        game_id = str(game["game_id"])
        home = str(game["home_team"])
        away = str(game["away_team"])
        base_efficiency = providers.get("team_efficiency_pace")

        def _priors():
            if season not in returning_cache:
                returning_cache[season] = fetch_returning_production(season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            if season not in talent_cache:
                talent_cache[season] = fetch_team_talent(season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            return returning_cache[season], talent_cache[season]

        def efficiency_with_priors(requested_game_id: str, as_of: datetime):
            base = None if base_efficiency is None else base_efficiency(requested_game_id, as_of)
            (returning, returning_uri, returning_sha), (talent, talent_uri, talent_sha) = _priors()
            home_prior = {"returning_production": returning.get(home), "talent": talent.get(home)}
            away_prior = {"returning_production": returning.get(away), "talent": talent.get(away)}
            if base is None and not any(home_prior.values()) and not any(away_prior.values()):
                return None
            payload = dict((base or {}).get("payload") or {})
            payload.update({
                "game_id": game_id,
                "season_priors": {"home": home_prior, "away": away_prior},
                "season_priors_scope": "LIVE_CONTEXT_ONLY_UNTIL_HISTORICAL_PIT_PUBLICATION_TIMES_ARE_ARCHIVED",
            })
            hashes = [returning_sha, talent_sha]
            if base is not None:
                hashes.append(str(base.get("source_sha256") or ""))
            return {
                "status": "AVAILABLE",
                "payload": payload,
                "source_name": "CFBD_ADVANCED_PRIOR_ONLY+RETURNING_PRODUCTION+TEAM_TALENT",
                "source_uri": returning_uri,
                "source_sha256": canonical_json_sha256(sorted(hashes)),
                "observed_at": as_of,
                "secondary_source_uri": talent_uri,
            }

        def prior_usage_provider(requested_game_id: str, as_of: datetime):
            if season not in usage_cache:
                usage_cache[season] = fetch_prior_season_player_usage(season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            if season not in roster_cache:
                roster_cache[season] = _fetch_fbs_roster_snapshot(season=season, cfbd_api_key=cfbd_api_key, opener=opener)
            usage_rows, usage_uri, usage_sha = usage_cache[season]
            rosters, roster_uri, roster_sha = roster_cache[season]
            home_rows = match_usage_to_current_roster(usage_rows=usage_rows, current_roster_rows=rosters.get(home) or [], current_team=home)
            away_rows = match_usage_to_current_roster(usage_rows=usage_rows, current_roster_rows=rosters.get(away) or [], current_team=away)
            if not home_rows and not away_rows:
                return None
            payload = {
                "game_id": game_id,
                "home": home_rows,
                "away": away_rows,
                "usage_scope": "PRIOR_SEASON_BASELINE_ONLY",
                "current_role_confirmed": False,
                "current_snap_share_confirmed": False,
                "transfer_identity_preserved_by_cfbd_athlete_id": True,
            }
            return {
                "status": "PARTIAL_PRIOR_SEASON_BASELINE",
                "payload": payload,
                "source_name": "CFBD_PRIOR_SEASON_PLAYER_USAGE+CURRENT_FBS_ROSTER_IDENTITY",
                "source_uri": usage_uri,
                "source_sha256": canonical_json_sha256(sorted([usage_sha, roster_sha])),
                "observed_at": as_of,
                "secondary_source_uri": roster_uri,
            }

        providers["team_efficiency_pace"] = efficiency_with_priors
        providers["player_usage_workload"] = prior_usage_provider
        return providers

    return factory
