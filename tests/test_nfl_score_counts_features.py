from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nfl.score_counts_features import (
    CONVERSION_PRIOR_TDS,
    DECAY,
    FG_MAKE_PRIOR_ATTEMPTS,
    ScoreCountFeatureError,
    TeamGame,
    _conversion_override,
    _field_goal_make_override,
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
        "offense_touchdowns", "made_field_goals", "field_goal_attempts", "def_st_touchdowns",
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
    assert h["field_goal_attempts"] == 1
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


def test_team_conversion_mix_uses_frozen_league_centered_prior():
    home_history = [TeamGame(offense_touchdowns=1, pat_made=1) for _ in range(50)]
    away_history = [TeamGame(offense_touchdowns=1, two_point_made=1) for _ in range(50)]
    all_history = home_history + away_history
    got = _conversion_override(team_history=home_history, all_completed_team_games=all_history)
    expected_pat = (50.0 + CONVERSION_PRIOR_TDS * 0.5) / (50.0 + CONVERSION_PRIOR_TDS)
    expected_two = (0.0 + CONVERSION_PRIOR_TDS * 0.5) / (50.0 + CONVERSION_PRIOR_TDS)
    assert got["conversion_pat_p"] == pytest.approx(expected_pat)
    assert got["conversion_two_p"] == pytest.approx(expected_two)
    assert got["conversion_no_p"] == pytest.approx(0.0)
    assert sum(got.values()) == pytest.approx(1.0)


def test_pbp_aggregation_is_single_pass_streamable():
    class OnePass:
        def __init__(self, rows):
            self.rows = rows
            self.used = False
        def __iter__(self):
            if self.used:
                raise AssertionError("PBP iterator consumed more than once")
            self.used = True
            yield from self.rows

    source = OnePass(pbp(n=2))
    teams, qbs = aggregate_game_pbp(source)
    assert ("g1", "H") in teams
    assert ("g2", "A") in teams
    assert ("g1", "QB-H") in qbs


def test_noncontiguous_game_rows_fail_closed_for_streaming_contract():
    rows = pbp(n=2)
    g1 = [row for row in rows if row["game_id"] == "g1"]
    g2 = [row for row in rows if row["game_id"] == "g2"]
    bad = [*g1[:2], *g2, *g1[2:]]
    with pytest.raises(ScoreCountFeatureError, match="PBP_GAME_ROWS_NOT_CONTIGUOUS"):
        aggregate_game_pbp(bad)


def test_csv_numeric_string_flags_are_parsed_as_boolean_indicators():
    from sportsedge.sports.nfl.score_counts_features import _flag

    assert _flag("1.0") is True
    assert _flag("1") is True
    assert _flag("0.0") is False
    assert _flag("0") is False
    assert _flag("") is False


def test_frozen_pit_ne_comment_is_not_a_scrimmage_play_after_projection():
    from sportsedge.sports.nfl.score_counts_source_projection import project_pbp_row

    row = project_pbp_row({
        "game_id": "2019_01_PIT_NE", "play_id": "4225",
        "posteam": "PIT", "defteam": "NE", "play_type_nfl": "COMMENT",
        "pass": "1", "rush": "0", "qb_dropback": "", "epa": "",
        "spread_line": -5.5,
    })
    assert "spread_line" not in row
    assert aggregate_game_pbp([row]) == ({}, {})


def test_missing_epa_retains_counts_without_diluting_observed_rates():
    from sportsedge.sports.nfl.score_counts_features import _team_features, _qb_prior
    observed = _pass("g1", 1, "H", "A", "QB-H", 2.0)
    missing = _pass("g1", 2, "H", "A", "QB-H", "", td=True, td_team="H")
    missing.update(sack=1, interception=1, success=0)
    teams, qbs = aggregate_game_pbp([observed, missing])
    off, defense = teams[("g1", "H")], teams[("g1", "A")]
    assert (off.off_plays, off.pass_dropbacks, off.offense_touchdowns) == (2, 2, 1)
    assert (off.sacks_allowed, off.turnovers) == (1, 1)
    assert (off.off_epa_n, off.pass_epa_n, off.off_success) == (1, 1, 1)
    assert (defense.def_plays, defense.def_epa_n, defense.def_pass_epa_n) == (2, 1, 1)
    features = _team_features([off] * 4)
    assert features["off_epa_per_play"] == pytest.approx(2.0)
    assert features["off_success_rate"] == pytest.approx(1.0)
    assert features["off_plays_per_game"] == pytest.approx(2.0)
    assert features["off_sack_rate_allowed"] == pytest.approx(0.5)
    qb = qbs[("g1", "QB-H")]
    assert (qb.dropbacks, qb.epa_n, qb.epa_sum) == (2, 1, 2.0)
    history = {(f"g{i}", "QB-H"): qb for i in range(10)}
    epa, _, count = _qb_prior(player_id="QB-H", prior_game_ids={f"g{i}" for i in range(10)}, game_qbs=history)
    assert epa == pytest.approx(2.0)
    assert count == 20


def test_missing_epa_does_not_relax_identity_checks():
    row = _pass("g1", 1, "", "A", "QB-H", "")
    with pytest.raises(ScoreCountFeatureError, match="SCRIMMAGE_IDENTITY_OR_EPA_MISSING"):
        aggregate_game_pbp([row])


def test_missing_rush_epa_uses_separate_denominator():
    base = {"game_id": "g1", "posteam": "H", "defteam": "A", "rush": 1}
    teams, _ = aggregate_game_pbp([
        {**base, "play_id": "1", "epa": 3.0},
        {**base, "play_id": "2", "epa": ""},
    ])
    assert teams[("g1", "H")].rush_attempts == 2
    assert teams[("g1", "H")].rush_epa_n == 1
    assert teams[("g1", "A")].def_rush_epa_n == 1


def test_missing_epa_policy_is_bound_to_attempt_identity_and_parent_bytes():
    import hashlib
    import json
    from pathlib import Path
    from scripts.run_nfl_score_counts_attempt import IDENTITY_PATHS
    path = "config/research/nfl_score_counts_g1_missing_epa_addendum_v3.json"
    assert path in IDENTITY_PATHS
    policy = json.loads(Path(path).read_text())
    for parent, digest in policy["parents_sha256"].items():
        assert hashlib.sha256(Path(parent).read_bytes()).hexdigest() == digest
    assert policy["attempt_accounting"]["next_attempt"] == 1
    assert policy["attempt_accounting"]["changes_model_inputs"] is True


def test_frozen_pit_ne_completion_keeps_factual_dropback():
    from sportsedge.sports.nfl.score_counts_source_projection import project_pbp_row
    teams, qbs = aggregate_game_pbp([project_pbp_row({
        "game_id": "2019_01_PIT_NE", "play_id": "4166",
        "posteam": "PIT", "defteam": "NE", "play_type_nfl": "PASS",
        "pass": "1", "rush": "0", "qb_dropback": "1",
        "epa": "", "qb_epa": "", "passer_player_id": "00-0022924",
    })])
    assert teams[("2019_01_PIT_NE", "PIT")].pass_dropbacks == 1
    assert teams[("2019_01_PIT_NE", "PIT")].pass_epa_n == 0
    assert qbs[("2019_01_PIT_NE", "00-0022924")].dropbacks == 1
    assert qbs[("2019_01_PIT_NE", "00-0022924")].epa_n == 0



def test_field_goal_attempts_count_made_missed_and_blocked():
    rows = [
        {
            "game_id": "g1", "play_id": "1",
            "posteam": "H", "defteam": "A",
            "field_goal_result": "made",
        },
        {
            "game_id": "g1", "play_id": "2",
            "posteam": "H", "defteam": "A",
            "field_goal_result": "missed",
        },
        {
            "game_id": "g1", "play_id": "3",
            "posteam": "H", "defteam": "A",
            "field_goal_result": "blocked",
        },
    ]
    teams, _ = aggregate_game_pbp(rows)
    home = teams[("g1", "H")]
    away = teams[("g1", "A")]
    assert home.field_goal_attempts == 3
    assert home.made_field_goals == 1
    assert away.field_goal_attempts_allowed == 3
    assert away.field_goals_allowed == 1


def test_unknown_nonempty_field_goal_result_fails_closed():
    with pytest.raises(ScoreCountFeatureError, match="FIELD_GOAL_RESULT_INVALID"):
        aggregate_game_pbp([{
            "game_id": "g1", "play_id": "1",
            "posteam": "H", "defteam": "A",
            "field_goal_result": "unknown",
        }])


def test_field_goal_make_rate_uses_frozen_decay_and_league_prior():
    team = [
        TeamGame(made_field_goals=1, field_goal_attempts=1),
        TeamGame(made_field_goals=0, field_goal_attempts=1),
    ]
    league = [
        TeamGame(made_field_goals=1, field_goal_attempts=2)
        for _ in range(10)
    ]
    got = _field_goal_make_override(
        team_history=team,
        all_completed_team_games=league,
    )
    weighted_makes = DECAY * 1.0 + 1.0 * 0.0
    weighted_attempts = DECAY * 1.0 + 1.0 * 1.0
    expected = (
        weighted_makes + FG_MAKE_PRIOR_ATTEMPTS * 0.5
    ) / (
        weighted_attempts + FG_MAKE_PRIOR_ATTEMPTS
    )
    assert got["fg_make_rate_shrunk"] == pytest.approx(expected)


def test_training_and_forward_rows_include_attempt3_pregame_features():
    history = rows_for()
    row = by_game_team(history, "g5", "H")
    assert "fg_attempts_per_game" in row
    assert "opp_fg_attempts_allowed_per_game" in row
    assert 0.0 <= row["fg_make_rate_shrunk"] <= 1.0
    assert "field_goal_attempts" in row

    sched = schedule(n=6)
    target_start = datetime.fromisoformat(sched[-1]["game_start_ts"])
    forward = build_score_count_forward_rows(
        schedule_rows=sched,
        pbp_rows=pbp(n=5),
        depth_rows=depth(n=6),
        target_game_ids=["g6"],
        as_of=target_start - timedelta(days=1),
        seasons=[2020],
    )
    assert len(forward) == 2
    assert all("field_goal_attempts" not in x for x in forward)
    assert all("fg_attempts_per_game" in x for x in forward)
    assert all("opp_fg_attempts_allowed_per_game" in x for x in forward)
    assert all("fg_make_rate_shrunk" in x for x in forward)
