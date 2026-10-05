import copy

import pytest

from sportsedge.sports.nfl.score_counts_scoring_prior import (
    ScoreCountScoringPriorError,
    build_scoring_composition_prior_artifact,
    score_count_rows_to_scoring_rows,
    scoring_composition_prior_from_artifact,
)


def row(**kw):
    base = {
        "game_id": "2025_01_A_B",
        "season": 2025,
        "week": 1,
        "game_start_ts": "2025-09-07T17:00:00Z",
        "team": "A",
        "opponent": "B",
        "offense_touchdowns": 2,
        "def_st_touchdowns": 0,
        "made_field_goals": 2,
        "safeties": 0,
        "pat_made": 2,
        "two_point_made": 0,
        "no_conversion": 0,
    }
    base.update(kw)
    return base


def test_score_count_adapter_reconstructs_exact_scoring_rows():
    rows = score_count_rows_to_scoring_rows(
        [
            row(),
            row(
                team="B",
                offense_touchdowns=1,
                pat_made=0,
                made_field_goals=1,
            ),
        ],
        as_of="2026-10-05T12:00:00Z",
    )
    assert rows[0]["score"] == 20
    assert rows[0]["touchdowns"] == 2
    assert rows[0]["extra_points_made"] == 2
    assert rows[0]["field_goals_made"] == 2
    assert rows[1]["score"] == 9


def test_artifact_round_trip_preserves_empirical_compositions():
    artifact = build_scoring_composition_prior_artifact(
        [
            row(),
            row(
                team="B",
                offense_touchdowns=1,
                pat_made=0,
                made_field_goals=1,
            ),
        ],
        as_of="2026-10-05T12:00:00Z",
        source_manifest_sha256="a" * 64,
        code_identity="score-count-test",
    )
    prior = scoring_composition_prior_from_artifact(artifact)
    assert prior.training_rows == 2
    assert prior.counts_by_score[20][(2, 2, 0, 2, 0)] == 1
    assert prior.counts_by_score[9][(1, 0, 0, 1, 0)] == 1
    assert artifact["market_data_used"] is False
    assert artifact["authority"]["official"] is False


def test_market_inputs_fail_closed():
    with pytest.raises(ScoreCountScoringPriorError, match="MARKET_INPUT_FORBIDDEN"):
        score_count_rows_to_scoring_rows(
            [row(odds=-110)],
            as_of="2026-10-05T12:00:00Z",
        )


def test_conservative_completion_cutoff_fails_closed():
    with pytest.raises(ScoreCountScoringPriorError, match="PIT_FUTURE"):
        score_count_rows_to_scoring_rows(
            [row(game_start_ts="2026-10-05T10:00:00Z")],
            as_of="2026-10-05T12:00:00Z",
        )


def test_artifact_digest_tamper_fails_closed():
    artifact = build_scoring_composition_prior_artifact(
        [row()],
        as_of="2026-10-05T12:00:00Z",
        source_manifest_sha256="b" * 64,
        code_identity="score-count-test",
    )
    broken = copy.deepcopy(artifact)
    broken["counts_by_score"]["20"][0]["count"] = 2
    with pytest.raises(ScoreCountScoringPriorError, match="ARTIFACT_DIGEST_MISMATCH"):
        scoring_composition_prior_from_artifact(broken)
