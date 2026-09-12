from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.settle_nfl_v2g_prospective_outcomes import (
    OutcomeError,
    build_outcome,
    outcome_sha256,
    validate_outcome,
)
from sportsedge.sports.nfl.m2_v2g_forward import prediction_sha256


ARTIFACT_SHA = "a" * 64
CODE_SHA = "b" * 40
SCHEDULE_SHA = "c" * 64


def _prediction(*, kickoff="2026-09-13T17:00:00+00:00"):
    record = {
        "schema_version": "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1",
        "status": "PROSPECTIVE_RESEARCH_PREDICTION_CAPTURED",
        "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
        "artifact_sha256": ARTIFACT_SHA,
        "implementation_commit_sha": "d" * 40,
        "candidate_source_git_blob_sha1": "e" * 40,
        "preregistration_commit_sha": "f" * 40,
        "capture_code_git_sha": CODE_SHA,
        "schedule_snapshot_sha256": "1" * 64,
        "game_id": "2026_01_ATL_PIT",
        "season": 2026,
        "week": 1,
        "kickoff_utc": kickoff,
        "captured_at_utc": "2026-09-12T12:50:13+00:00",
        "home_team": "PIT",
        "away_team": "ATL",
        "summary": {
            "home_win_probability": 0.5,
            "tie_probability": 0.02,
            "away_win_probability": 0.48,
            "expected_home_score": 21.0,
            "expected_away_score": 20.0,
        },
        "score_distribution": [
            {"home_score": 21, "away_score": 20, "margin": 1, "total": 41, "weight": 1.0}
        ],
        "historical_data_role": "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT",
        "market_prices_consumed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    record["prediction_sha256"] = prediction_sha256(record)
    return record


def _schedule_row(**overrides):
    row = {
        "game_id": "2026_01_ATL_PIT",
        "home_team": "PIT",
        "away_team": "ATL",
        "home_score": "27",
        "away_score": "20",
    }
    row.update(overrides)
    return row


def test_outcome_binds_prediction_and_objective_score_only():
    record = build_outcome(
        prediction=_prediction(),
        schedule_row=_schedule_row(),
        schedule_sha256=SCHEDULE_SHA,
        settlement_code_git_sha=CODE_SHA,
        observed_at_utc="2026-09-14T03:00:00+00:00",
        min_hours_after_kickoff=8.0,
    )
    assert record is not None
    assert record["home_score"] == 27
    assert record["away_score"] == 20
    assert record["final_margin_home_minus_away"] == 7
    assert record["final_total"] == 47
    assert record["prediction_sha256"] == _prediction()["prediction_sha256"]
    assert record["market_prices_consumed"] is False
    assert record["promotion_authority"] is False
    assert record["may_create_model_p"] is False
    assert validate_outcome(record) == record["outcome_sha256"]


def test_outcome_waits_until_frozen_postgame_delay():
    record = build_outcome(
        prediction=_prediction(),
        schedule_row=_schedule_row(),
        schedule_sha256=SCHEDULE_SHA,
        settlement_code_git_sha=CODE_SHA,
        observed_at_utc="2026-09-13T23:00:00+00:00",
        min_hours_after_kickoff=8.0,
    )
    assert record is None


def test_outcome_never_accepts_delay_shorter_than_five_hours():
    with pytest.raises(OutcomeError, match="NFL_V2G_OUTCOME_MIN_DELAY_TOO_SHORT"):
        build_outcome(
            prediction=_prediction(),
            schedule_row=_schedule_row(),
            schedule_sha256=SCHEDULE_SHA,
            settlement_code_git_sha=CODE_SHA,
            observed_at_utc="2026-09-14T03:00:00+00:00",
            min_hours_after_kickoff=4.99,
        )


def test_outcome_leaves_blank_scores_pending_without_imputation():
    record = build_outcome(
        prediction=_prediction(),
        schedule_row=_schedule_row(home_score="", away_score=""),
        schedule_sha256=SCHEDULE_SHA,
        settlement_code_git_sha=CODE_SHA,
        observed_at_utc="2026-09-14T03:00:00+00:00",
    )
    assert record is None


def test_outcome_fails_closed_on_schedule_identity_mismatch():
    with pytest.raises(OutcomeError, match="NFL_V2G_OUTCOME_HOME_TEAM_MISMATCH"):
        build_outcome(
            prediction=_prediction(),
            schedule_row=_schedule_row(home_team="XXX"),
            schedule_sha256=SCHEDULE_SHA,
            settlement_code_git_sha=CODE_SHA,
            observed_at_utc="2026-09-14T03:00:00+00:00",
        )


def test_outcome_hash_detects_mutation():
    record = build_outcome(
        prediction=_prediction(),
        schedule_row=_schedule_row(),
        schedule_sha256=SCHEDULE_SHA,
        settlement_code_git_sha=CODE_SHA,
        observed_at_utc="2026-09-14T03:00:00+00:00",
    )
    assert record is not None
    mutated = dict(record, home_score=28)
    with pytest.raises(OutcomeError, match="NFL_V2G_OUTCOME_SHA_MISMATCH"):
        validate_outcome(mutated)


def test_outcome_hash_is_canonical_and_self_excluding():
    record = build_outcome(
        prediction=_prediction(),
        schedule_row=_schedule_row(),
        schedule_sha256=SCHEDULE_SHA,
        settlement_code_git_sha=CODE_SHA,
        observed_at_utc="2026-09-14T03:00:00+00:00",
    )
    assert record is not None
    assert outcome_sha256(record) == record["outcome_sha256"]
