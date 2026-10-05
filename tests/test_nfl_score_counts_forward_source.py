from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.score_counts_forward_source import (
    ScoreCountForwardSourceError,
    build_forward_source_manifest,
    project_depth_rows,
    project_schedule_rows,
    select_forward_targets,
)


def schedule_rows():
    return [
        {
            "game_id": "2026_05_A_B",
            "season": "2026",
            "week": "5",
            "game_type": "REG",
            "gameday": "2026-10-08",
            "gametime": "20:15",
            "home_team": "B",
            "away_team": "A",
            "spread_line": "-3.5",
            "total_line": "44.5",
        },
        {
            "game_id": "2026_05_C_D",
            "season": "2026",
            "week": "5",
            "game_type": "REG",
            "gameday": "2026-10-11",
            "gametime": "13:00",
            "home_team": "D",
            "away_team": "C",
            "spread_line": "2.5",
        },
        {
            "game_id": "2026_04_X_Y",
            "season": "2026",
            "week": "4",
            "game_type": "REG",
            "gameday": "2026-10-01",
            "gametime": "20:15",
            "home_team": "Y",
            "away_team": "X",
        },
    ]


def test_schedule_projection_strips_market_columns():
    rows = project_schedule_rows(schedule_rows())
    assert rows[0]["game_id"] == "2026_05_A_B"
    assert "spread_line" not in rows[0]
    assert "total_line" not in rows[0]


def test_depth_projection_is_explicit_allowlist():
    rows = project_depth_rows([
        {
            "dt": "2026-10-05T12:00:00Z",
            "season": 2026,
            "week": 5,
            "team": "B",
            "pos_abb": "QB",
            "pos_rank": 1,
            "gsis_id": "QB1",
            "odds": -110,
        }
    ])
    assert rows == [{
        "dt": "2026-10-05T12:00:00Z",
        "season": 2026,
        "week": 5,
        "team": "B",
        "pos_abb": "QB",
        "pos_rank": 1,
        "gsis_id": "QB1",
    }]


def test_target_selection_is_future_week5_plus_only():
    projected = project_schedule_rows(schedule_rows())
    targets = select_forward_targets(
        projected,
        as_of="2026-10-05T16:00:00Z",
        horizon_days=7,
    )
    assert targets == ["2026_05_A_B", "2026_05_C_D"]

    with pytest.raises(
        ScoreCountForwardSourceError,
        match="EXPLICIT_TARGET_NOT_ELIGIBLE",
    ):
        select_forward_targets(
            projected,
            as_of="2026-10-05T16:00:00Z",
            horizon_days=7,
            explicit_game_ids=["2026_04_X_Y"],
        )


def test_forward_manifest_binds_raw_bytes_parser_and_fit_provenance():
    out = build_forward_source_manifest(
        [
            {
                "name": "pbp_2026_snapshot",
                "source_uri": "https://example.test/pbp.csv.gz",
                "retrieved_at_utc": "2026-10-05T16:00:00Z",
                "byte_sha256": "1" * 64,
                "season_scope": [2026],
            },
            {
                "name": "pbp_2025_frozen",
                "source_uri": "https://example.test/pbp2025.csv.gz",
                "retrieved_at_utc": "2026-10-05T16:00:00Z",
                "byte_sha256": "2" * 64,
                "immutable_expected_sha256": "2" * 64,
                "season_scope": [2025],
            },
        ],
        prediction_at=datetime(2026, 10, 5, 16, tzinfo=timezone.utc),
        target_game_ids=["2026_05_A_B"],
        fit_artifact_sha256="a" * 64,
        fit_training_source_manifest_sha256="b" * 64,
        serving_code_identity="c" * 64,
    )
    assert len(out["manifest_sha256"]) == 64
    assert out["fit_training_source_manifest_sha256"] == "b" * 64
    assert out["market_columns_projected_out_before_feature_builder"] is True
    assert all(
        row["parser_code_sha256"] == "c" * 64
        for row in out["receipts"]
    )


def test_immutable_receipt_sha_mismatch_fails_closed():
    with pytest.raises(
        ScoreCountForwardSourceError,
        match="IMMUTABLE_SOURCE_SHA_MISMATCH",
    ):
        build_forward_source_manifest(
            [{
                "name": "pbp_2025_frozen",
                "source_uri": "https://example.test/pbp2025.csv.gz",
                "retrieved_at_utc": "2026-10-05T16:00:00Z",
                "byte_sha256": "1" * 64,
                "immutable_expected_sha256": "2" * 64,
                "season_scope": [2025],
            }],
            prediction_at="2026-10-05T16:00:00Z",
            target_game_ids=["2026_05_A_B"],
            fit_artifact_sha256="a" * 64,
            fit_training_source_manifest_sha256="b" * 64,
            serving_code_identity="c" * 64,
        )
