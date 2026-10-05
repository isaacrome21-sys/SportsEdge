from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nfl.score_counts_features import (
    ScoreCountFeatureError,
    aggregate_game_pbp,
    build_score_count_training_rows,
)


def schedule(n=7):
    start = datetime(2020, 9, 6, 17, 0, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        out.append({
            "game_id": f"g{i+1}",
            "season": 2020,
            "week": i + 1,
            "game_start_ts": (start + timedelta(days=7 * i)).isoformat(),
            "home_team": "H",
            "away_team": "A",
            # Physically present upstream market fields must be ignored.
            "spread_line": -3.5 + i,
            "total_line": 44.5 + i,
        })
    return out


def depth(n=7):
    out = []
    for week in range(1, n + 1):
        out.extend([
            {
                "season": 2020, "week": week, "club_code": "H",
                "game_type": "REG", "depth_team": 1, "position": "QB",
                "gsis_id": "QB-H",
            },
            {
                "season": 2020, "week": week, "club_code": "A",
                "game_type": "REG", "depth_team": 1, "position": "QB",
                "gsis_id": "QB-A",
            },
        ])
    return out


def _pass(gid, play, offense, defense, qb, epa, *, td=False, td_team=None, cpoe=1.0):
    row = {
        "game_id": gid,
        "play_id": str(play),
        "posteam": offense,
        "defteam": defense,
        "pass": 1,
        "qb_dropback": 1,
        "rush_attempt": 0,
        "epa": epa,
        "qb_epa": epa,
        "cpoe": cpoe,
        "passer_player_id": qb,
        "sack": 0,
        "interception": 0,
        "fumble_lost": 0,
        "touchdown": int(td),
        "return_touchdown": 0,
    }
    if td_team is not None:
        row["td_team"] = td_team
    return row


def pbp(n=7):
    rows = []
    for i in range(n):
        gid = f"g{i+1}"
        base = 100 * (i + 1)
        # Five prior dropbacks per QB per game => 20 after four games.
        for j in range(5):
            rows.append(_pass(
                gid, base + j, "H", "A", "QB-H",
                0.10 + 0.01 * i + 0.001 * j,
                td=(j == 0), td_team="H" if j == 0 else None,
                cpoe=2.0 + 0.1 * j,
            ))
            rows.append(_pass(
                gid, base + 20 + j, "A", "H", "QB-A",
                -0.02 + 0.005 * i + 0.001 * j,
                td=(j == 1), td_team="A" if j == 1 else None,
                cpoe=-1.0 + 0.1 * j,
            ))

        rows.extend([
            {
                "game_id": gid, "play_id": str(base + 50),
                "posteam": "H", "defteam": "A",
                "field_goal_result": "made",
            },
            {
                "game_id": gid, "play_id": str(base + 51),
                "posteam": "H", "defteam": "A",
                "extra_point_result": "good",
            },
            {
                "game_id": gid, "play_id": str(base + 52),
                "posteam": "A", "defteam": "H",
                "two_point_conv_result": "success",
            },
        ])
    return rows


def rows_for(pbp_rows=None, schedule_rows=None, depth_rows=None):
    return build_score_count_training_rows(
        schedule_rows=schedule_rows or schedule(),
        pbp_rows=pbp_rows or pbp(),
        depth_rows=depth_rows or depth(),
        seasons=[2020],
    )


def by_game_team(rows, gid, team):
    return next(row for row in rows if row["game_id"] == gid and row["team"] == team)


def feature_view(row):
    excluded = {
        "game_id", "season", "week", "game_start_ts", "team", "opponent",
        "starting_qb_id", "starting_qb_prior_dropbacks",
        "offense_touchdowns", "made_field_goals", "def_st_touchdowns",
        "safeties", "pat_made", "two_point_made",
    }
    return {k: v for k, v in row.items() if k not in excluded}


def test_first_eligible_game_uses_only_four_prior_games():
    out = rows_for()
    assert {row["game_id"] for row in out} == {"g5", "g6", "g7"}
    g5h = by_game_team(out, "g5", "H")
    g5a = by_game_team(out, "g5", "A")
    assert g5h["starting_qb_prior_dropbacks"] == 20
    assert g5a["starting_qb_prior_dropbacks"] == 20


def test_target_game_pbp_cannot_change_its_own_features_but_changes_next_game():
    original = rows_for()
    changed_pbp = deepcopy(pbp())
    for row in changed_pbp:
        if row["game_id"] == "g5" and row.get("posteam") == "H" and row.get("epa") is not None:
            row["epa"] = 50.0
            row["qb_epa"] = 50.0
            row["cpoe"] = 25.0
    changed = rows_for(pbp_rows=changed_pbp)

    assert feature_view(by_game_team(original, "g5", "H")) == feature_view(by_game_team(changed, "g5", "H"))
    assert feature_view(by_game_team(original, "g6", "H")) != feature_view(by_game_team(changed, "g6", "H"))


def test_schedule_market_fields_are_ignored_by_predictive_rows():
    a = rows_for()
    mutated = deepcopy(schedule())
    for i, row in enumerate(mutated):
        row["spread_line"] = 1000 + i
        row["total_line"] = 2000 + i
        row["home_spread_odds"] = -999
        row["over_odds"] = 999
    b = rows_for(schedule_rows=mutated)
    assert a == b


def test_pbp_market_field_is_rejected_because_pbp_feeds_predictive_state():
    bad = deepcopy(pbp())
    bad[0]["sportsbook_price"] = -110
    with pytest.raises(ScoreCountFeatureError, match="MARKET_FIELD_FORBIDDEN"):
        rows_for(pbp_rows=bad)


def test_scoring_event_labels_classify_offense_return_safety_and_conversions():
    custom = pbp(n=5)
    # Defensive return TD for H in g5.
    custom.append({
        "game_id": "g5", "play_id": "599",
        "posteam": "A", "defteam": "H",
        "touchdown": 1, "td_team": "H", "return_touchdown": 1,
    })
    # Safety scored by A defense.
    custom.append({
        "game_id": "g5", "play_id": "598",
        "posteam": "H", "defteam": "A", "safety": 1,
    })
    out = build_score_count_training_rows(
        schedule_rows=schedule(n=5),
        pbp_rows=custom,
        depth_rows=depth(n=5),
        seasons=[2020],
    )
    h = by_game_team(out, "g5", "H")
    a = by_game_team(out, "g5", "A")
    assert h["offense_touchdowns"] == 1
    assert a["offense_touchdowns"] == 1
    assert h["def_st_touchdowns"] == 1
    assert a["safeties"] == 1
    assert h["made_field_goals"] == 1
    assert h["pat_made"] == 1
    assert a["two_point_made"] == 1


def test_missing_td_team_fails_closed():
    bad = pbp(n=1)
    bad[0]["touchdown"] = 1
    bad[0].pop("td_team", None)
    with pytest.raises(ScoreCountFeatureError, match="TD_TEAM_REQUIRED"):
        aggregate_game_pbp(bad)


def test_duplicate_play_id_fails_closed():
    bad = pbp(n=1)
    bad.append(dict(bad[0]))
    with pytest.raises(ScoreCountFeatureError, match="DUPLICATE_PLAY"):
        aggregate_game_pbp(bad)


def test_insufficient_qb_prior_fails_closed_without_partial_game_row():
    sparse = pbp(n=5)
    # Leave only 4 dropbacks per QB per each of the first four games => 16 prior.
    sparse = [
        row for row in sparse
        if not (
            row["game_id"] in {"g1", "g2", "g3", "g4"}
            and row.get("qb_dropback") == 1
            and int(row["play_id"]) % 100 in {4, 24}
        )
    ]
    out = build_score_count_training_rows(
        schedule_rows=schedule(n=5),
        pbp_rows=sparse,
        depth_rows=depth(n=5),
        seasons=[2020],
    )
    assert out == []


def test_rare_score_context_is_strictly_prior_and_updates_next_game():
    original = rows_for()
    changed_pbp = deepcopy(pbp())
    changed_pbp.extend([
        {
            "game_id": "g5", "play_id": "5901",
            "posteam": "A", "defteam": "H",
            "touchdown": 1, "td_team": "H", "return_touchdown": 1,
        },
        {
            "game_id": "g5", "play_id": "5902",
            "posteam": "H", "defteam": "A", "safety": 1,
        },
    ])
    changed = rows_for(pbp_rows=changed_pbp)

    g5_h_a = by_game_team(original, "g5", "H")
    g5_h_b = by_game_team(changed, "g5", "H")
    g5_a_a = by_game_team(original, "g5", "A")
    g5_a_b = by_game_team(changed, "g5", "A")
    assert g5_h_a["def_st_td_rate"] == g5_h_b["def_st_td_rate"]
    assert g5_a_a["safety_rate"] == g5_a_b["safety_rate"]

    g6_h_a = by_game_team(original, "g6", "H")
    g6_h_b = by_game_team(changed, "g6", "H")
    g6_a_a = by_game_team(original, "g6", "A")
    g6_a_b = by_game_team(changed, "g6", "A")
    assert g6_h_b["def_st_td_rate"] > g6_h_a["def_st_td_rate"]
    assert g6_a_b["safety_rate"] > g6_a_a["safety_rate"]


def test_conversion_context_uses_league_until_50_team_opportunities_then_team_rate():
    out = build_score_count_training_rows(
        schedule_rows=schedule(n=52),
        pbp_rows=pbp(n=52),
        depth_rows=depth(n=52),
        seasons=[2020],
    )
    early_h = by_game_team(out, "g5", "H")
    early_a = by_game_team(out, "g5", "A")
    assert early_h["conversion_pat_p"] == pytest.approx(0.5)
    assert early_h["conversion_two_p"] == pytest.approx(0.5)
    assert early_a["conversion_pat_p"] == pytest.approx(0.5)
    assert early_a["conversion_two_p"] == pytest.approx(0.5)

    mature_h = by_game_team(out, "g51", "H")
    mature_a = by_game_team(out, "g51", "A")
    assert mature_h["conversion_pat_p"] == pytest.approx(1.0)
    assert mature_h["conversion_two_p"] == pytest.approx(0.0)
    assert mature_a["conversion_pat_p"] == pytest.approx(0.0)
    assert mature_a["conversion_two_p"] == pytest.approx(1.0)
