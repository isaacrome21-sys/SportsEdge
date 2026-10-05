import pytest

from sportsedge.sports.nfl.score_counts_scoring_prior import (
    ScoreCountScoringPriorError,
    build_scoring_composition_rows,
)


def schedule(score_h=10, score_a=7, gid="g1"):
    return [{
        "game_id": gid,
        "season": 2025,
        "week": 1,
        "game_start_ts": "2025-09-01T17:00:00+00:00",
        "home_team": "H",
        "away_team": "A",
        "home_score": score_h,
        "away_score": score_a,
        # Market fields may exist in the provider schedule but never enter rows.
        "spread_line": -3.0,
        "total_line": 44.5,
    }]


def pbp(gid="g1"):
    return [
        {"game_id": gid, "play_id": "1", "posteam": "H", "defteam": "A", "touchdown": 1, "td_team": "H"},
        {"game_id": gid, "play_id": "2", "posteam": "H", "defteam": "A", "extra_point_result": "good"},
        {"game_id": gid, "play_id": "3", "posteam": "H", "defteam": "A", "field_goal_result": "made"},
        {"game_id": gid, "play_id": "4", "posteam": "A", "defteam": "H", "touchdown": 1, "td_team": "A"},
        {"game_id": gid, "play_id": "5", "posteam": "A", "defteam": "H", "extra_point_result": "good"},
    ]


def test_rows_reconstruct_exact_schedule_scores_and_stay_market_blind():
    rows = build_scoring_composition_rows(
        schedule_rows=schedule(),
        pbp_rows=pbp(),
        seasons=[2025],
        conservative_completion_lag_hours=24,
    )
    assert len(rows) == 2
    home = next(row for row in rows if row["team"] == "H")
    away = next(row for row in rows if row["team"] == "A")
    assert home["score"] == 10
    assert home["touchdowns"] == 1
    assert home["field_goals_made"] == 1
    assert away["score"] == 7
    assert all("spread" not in row and "total_line" not in row for row in rows)
    assert home["completed_at"] == "2025-09-02T17:00:00+00:00"


def test_schedule_score_mismatch_fails_closed():
    with pytest.raises(ScoreCountScoringPriorError, match="SCHEDULE_MISMATCH"):
        build_scoring_composition_rows(
            schedule_rows=schedule(score_h=11),
            pbp_rows=pbp(),
            seasons=[2025],
            conservative_completion_lag_hours=24,
        )


def test_explicit_nonfinal_game_exclusion_removes_suspended_game():
    rows = build_scoring_composition_rows(
        schedule_rows=schedule(gid="2022_17_BUF_CIN"),
        pbp_rows=pbp(gid="2022_17_BUF_CIN"),
        seasons=[2025],
        conservative_completion_lag_hours=24,
        excluded_game_ids=["2022_17_BUF_CIN"],
    )
    # The only PBP game was explicitly excluded, so fail closed instead of
    # silently producing an empty prior.
    assert rows == []
