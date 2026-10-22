"""Synthetic contract test: real-shaped Results Pull CSV rows -> audited V2.

No actual NBA data, captured quotes, or admission is represented here.
"""
from datetime import datetime, timedelta, timezone

from sportsedge.research.nba_early_season_evidence_join_v1 import join_nba_boxscore_evidence
from sportsedge.research.nba_early_season_prop_v2 import project_early_prop


def _observations():
    boxes, events, roles = [], [], []
    for season, count, month, day0, pts in [
        (2025, 8, 10, 1, 20), (2026, 1, 10, 20, 32),
    ]:
        for i in range(count):
            tip = datetime(season, month, day0 + i, 20, tzinfo=timezone.utc)
            gid = str(season) + "_" + str(i)
            boxes.append({
                "PLAYER_ID": "99", "GAME_ID": gid,
                "TEAM_ABBREVIATION": "NY",
                "SEASON": f"{season}-{(season+1)%100:02d}",
                "SEASON_TYPE_ID": "2", "MIN": "30:00",
                "PTS": str(pts), "REB": "5", "AST": "6",
            })
            events.append({
                "event_id": gid, "tipoff": tip.isoformat(),
                "finalized_at": (tip + timedelta(hours=2)).isoformat(),
                "result_observed_at": (tip + timedelta(hours=3)).isoformat(),
                "event_state": "FINAL", "result_state": "FINAL",
                "source_ref": "synthetic-event-receipt",
            })
            roles.append({
                "player_id": "99", "team_abbreviation": "NY",
                "position": "G",
                "observed_at": (tip - timedelta(hours=1)).isoformat(),
                "source_ref": "synthetic-role-receipt",
            })
    return boxes, events, roles


def test_join_output_is_consumable_by_distinct_v2_only():
    joined=join_nba_boxscore_evidence(*_observations())
    assert joined["joined"] == 9
    assert joined["receipt_authentication"] == "NOT_ESTABLISHED_BY_CALLER_FIELDS"
    assert all(
        g["finalized_at"] and g["role_observed_at"] and g["role_source_ref"]
        for g in joined["rows"]
    )
    candidate=project_early_prop(
        joined["rows"], player_id="99", target_team_id="NY",
        target_season=2026, target_date="2026-10-21",
        as_of="2026-10-21T17:00:00Z",
        stat="points", line=22.5,
    )
    assert candidate["status"] == "RESEARCH_PROJECTION"
    assert candidate["current_season_prior_games"] == 1
    assert candidate["previous_season_games"] == 8
    assert 20 < candidate["model_mean"] < 32
    assert candidate["play_authority"] is False
    assert candidate["market_test"] == "NOT_RUN"
