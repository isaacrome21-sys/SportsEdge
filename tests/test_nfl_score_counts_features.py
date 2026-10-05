from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nfl.score_counts_features import (
    ScoreCountFeatureError,
    aggregate_game_pbp,
    build_score_count_forward_rows,
    build_score_count_training_rows,
)


def schedule(n=7, season=2020):
    start = datetime(season, 9, 6, 17, 0, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        out.append({
            "game_id": f"g{i+1}",
            "season": season,
            "week": i + 1,
            "game_start_ts": (start + timedelta(days=7 * i)).isoformat(),
            "home_team": "H",
            "away_team": "A",
            "spread_line": -3.5 + i,
            "total_line": 44.5 + i,
        })
    return out


def depth(n=7, season=2020, *, timestamped=False):
    start = datetime(season, 9, 1, 12, 0, tzinfo=timezone.utc)
    out = []
    for week in range(1, n + 1):
        for team, qb in (("H", "QB-H"), ("A", "QB-A")):
            row = {
                "season": season,
                "week": week,
                "club_code": team,
                "team": team,
                "game_type": "REG",
                "depth_team": 1,
                "position": "QB",
                "pos_abb": "QB",
                "pos_rank": 1,
                "gsis_id": qb,
            }
            if timestamped:
                row["dt"] = (start + timedelta(days=7 * (week - 1))).isoformat()
            out.append(row)
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
        "safeties", "pat_made", "two_point_made", "no_conversion",
        "feature_digest", "prediction_at",
    }
    return {k: v for k, v in row.items() if k not in excluded}


def test_first_eligible_game_uses_only_four_prior_games():
    out = rows_for()
    assert {row["game_id"] for row in out} == {"g5", "g6", "g7"}
    g5h = by_game_team(out, "g5", "H")
    g5a = by_game_team(out, "g5", "A")
    assert g5h["starting_qb_prior_dropbacks"] == 20
    assert g5a["starting_qb_prior_dropbacks"] == 20
    assert g5h["feature_digest"]
    assert g5h["conversion_pat_p"] == pytest.approx(0.5)
    assert g5h["conversion_two_p"] == pytest.approx(0.5)
    assert g5h["conversion_no_p"] == pytest.approx(0.0)


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
    custom.append({
        "game_id": "g5", "play_id": "599",
        "posteam": "A", "defteam": "H",
        "touchdown": 1, "td_team": "H", "return_touchdown": 1,
    })
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
    assert h["no_conversion"] == 1


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


def test_forward_game_builds_without_target_pbp_and_has_no_labels():
    sched = schedule(n=6)
    target_start = datetime.fromisoformat(sched[-1]["game_start_ts"])
    out = build_score_count_forward_rows(
        schedule_rows=sched,
        pbp_rows=pbp(n=5),
        depth_rows=depth(n=6),
        target_game_ids=["g6"],
        as_of=target_start - timedelta(days=1),
        seasons=[2020],
    )
    assert len(out) == 2
    assert {row["game_id"] for row in out} == {"g6"}
    assert {row["team"] for row in out} == {"H", "A"}
    assert all("offense_touchdowns" not in row for row in out)
    assert all(row["prediction_at"] for row in out)
    assert all(row["feature_digest"] for row in out)
    assert all("def_st_td_rate" in row and "conversion_pat_p" in row for row in out)


def test_forward_target_pbp_is_explicit_leak_and_fails_closed():
    sched = schedule(n=6)
    target_start = datetime.fromisoformat(sched[-1]["game_start_ts"])
    with pytest.raises(ScoreCountFeatureError, match="FORWARD_TARGET_PBP_FORBIDDEN"):
        build_score_count_forward_rows(
            schedule_rows=sched,
            pbp_rows=pbp(n=6),
            depth_rows=depth(n=6),
            target_game_ids=["g6"],
            as_of=target_start - timedelta(days=1),
            seasons=[2020],
        )


def test_forward_asof_must_precede_target_kickoff():
    sched = schedule(n=6)
    target_start = datetime.fromisoformat(sched[-1]["game_start_ts"])
    with pytest.raises(ScoreCountFeatureError, match="FORWARD_TARGET_NOT_FUTURE"):
        build_score_count_forward_rows(
            schedule_rows=sched,
            pbp_rows=pbp(n=5),
            depth_rows=depth(n=6),
            target_game_ids=["g6"],
            as_of=target_start,
            seasons=[2020],
        )


def test_modern_forward_depth_snapshot_after_asof_cannot_be_used():
    sched = schedule(n=6, season=2026)
    target_start = datetime.fromisoformat(sched[-1]["game_start_ts"])
    rows = depth(n=6, season=2026, timestamped=True)
    # Move every week-6 depth receipt after prediction time. Earlier snapshots
    # remain admissible, so the latest known starter still resolves from week 5.
    asof = target_start - timedelta(days=1)
    for row in rows:
        if row["week"] == 6:
            row["dt"] = (asof + timedelta(hours=2)).isoformat()
    out = build_score_count_forward_rows(
        schedule_rows=sched,
        pbp_rows=pbp(n=5),
        depth_rows=rows,
        target_game_ids=["g6"],
        as_of=asof,
        seasons=[2026],
    )
    assert len(out) == 2
    assert {row["starting_qb_id"] for row in out} == {"QB-H", "QB-A"}
