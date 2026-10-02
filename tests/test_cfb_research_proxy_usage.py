from datetime import datetime, timezone

import pytest

from sportsedge.sports.cfb.research_proxy_usage import (
    CFBResearchProxyUsageError,
    build_research_proxy_live_features,
    build_team_proxy_usage,
    normalize_cfbd_usage_rows,
)
from sportsedge.sports.cfb.source import CFBGame


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _usage(team):
    return [
        {
            "season": 2026, "id": f"{team}-qb", "name": f"{team} QB",
            "position": "QB", "team": team, "conference": "X",
            "usage": {"overall": .51, "pass": .92, "rush": .17},
        },
        {
            "season": 2026, "id": f"{team}-rb", "name": f"{team} RB",
            "position": "RB", "team": team, "conference": "X",
            "usage": {"overall": .28, "pass": .08, "rush": .61},
        },
        {
            "season": 2026, "id": f"{team}-wr", "name": f"{team} WR",
            "position": "WR", "team": team, "conference": "X",
            "usage": {"overall": .22, "pass": .31, "rush": .02},
        },
        {
            "season": 2026, "id": f"{team}-te", "name": f"{team} TE",
            "position": "TE", "team": team, "conference": "X",
            "usage": {"overall": .12, "pass": .18, "rush": 0.0},
        },
    ]


def _teams():
    return [
        {"school": "Home", "abbreviation": "HOM", "mascot": "Homes", "alternateNames": []},
        {"school": "Away", "abbreviation": "AWY", "mascot": "Aways", "alternateNames": []},
    ]


def _game():
    return CFBGame(
        game_id="401",
        season=2026,
        week=6,
        start_ts="2026-10-02T18:00:00+00:00",
        home_team="Home",
        away_team="Away",
        neutral_site=False,
    )


def test_proxy_uses_observed_cfbd_shares_but_labels_missing_dimensions_as_assumptions():
    rows = normalize_cfbd_usage_rows(_usage("Home"), season=2026)
    team = build_team_proxy_usage(rows, team="Home")
    assert team["quarterback_id"] == "Home-qb"
    assert abs(sum(p["target_share"] for p in team["players"]) - 1.0) < 1e-12
    assert abs(sum(p["rush_share"] for p in team["players"]) - 1.0) < 1e-12
    assert all(p["snap_share"] == 1.0 for p in team["players"])
    assert all(p["red_zone_share"] == 1.0 for p in team["players"])
    assumptions = team["proxy_provenance"]["neutral_assumption_fields"]
    assert any("snap_share=1.0" in item for item in assumptions)
    assert any("route_participation=1.0" in item for item in assumptions)
    assert any("red_zone_share=1.0" in item for item in assumptions)


def test_same_day_proxy_is_zero_authority_and_identity_only():
    live = build_research_proxy_live_features(
        games=[_game()],
        team_rows=_teams(),
        player_usage_rows=_usage("Home") + _usage("Away"),
        provider_events=[{
            "id": "evt-1",
            "home_team": "Home",
            "away_team": "Away",
            "commence_time": "2026-10-02T18:00:00Z",
        }],
        season=2026,
        now=NOW,
        horizon_hours=24,
        allowed_model_teams={"Home", "Away"},
    )
    assert live["schema_version"] == "CFB_PROP_RESEARCH_PROXY_LIVE_FEATURES_V1"
    assert live["games"][0]["provider_event_id"] == "evt-1"
    gov = live["governance"]
    assert gov["research_proxy_usage"] is True
    assert gov["sportsbook_event_identity_only"] is True
    assert gov["sportsbook_prices_consumed"] is False
    assert gov["production_eligible"] is False
    assert gov["promotion_authority"] is False
    assert gov["official_eligible"] is False
    assert gov["true_snap_share_observed"] is False
    assert gov["true_route_participation_observed"] is False
    assert gov["true_red_zone_share_observed"] is False


def test_model_profile_mismatch_skips_game_fail_closed():
    with pytest.raises(CFBResearchProxyUsageError, match="NO_RUNNABLE"):
        build_research_proxy_live_features(
            games=[_game()],
            team_rows=_teams(),
            player_usage_rows=_usage("Home") + _usage("Away"),
            provider_events=[{
                "id": "evt-1",
                "home_team": "Home",
                "away_team": "Away",
                "commence_time": "2026-10-02T18:00:00Z",
            }],
            season=2026,
            now=NOW,
            allowed_model_teams={"Home"},
        )


def test_ambiguous_or_shifted_provider_identity_does_not_bind():
    with pytest.raises(CFBResearchProxyUsageError, match="NO_RUNNABLE"):
        build_research_proxy_live_features(
            games=[_game()],
            team_rows=_teams(),
            player_usage_rows=_usage("Home") + _usage("Away"),
            provider_events=[{
                "id": "evt-1",
                "home_team": "Home",
                "away_team": "Away",
                "commence_time": "2026-10-02T19:00:00Z",
            }],
            season=2026,
            now=NOW,
        )


def test_missing_target_pool_is_not_filled_with_fake_share():
    rows = _usage("Home")
    for row in rows:
        if row["position"] != "QB":
            row["usage"]["pass"] = 0.0
    normalized = normalize_cfbd_usage_rows(rows, season=2026)
    with pytest.raises(CFBResearchProxyUsageError, match="TARGET_POOL_EMPTY"):
        build_team_proxy_usage(normalized, team="Home")
