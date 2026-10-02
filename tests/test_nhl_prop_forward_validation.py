import pytest

from sportsedge.sports.nhl.prop_forward_validation import (
    EvaluationRow,
    NHLPropForwardValidationError,
    PredictionReceipt,
    Settlement,
    evaluate_market,
    join_rows,
    prediction_from_mapping,
)


SHA = "a" * 64


def prediction(**overrides):
    row = {
        "market": "PLAYER_SHOTS",
        "game_id": "2026020001",
        "subject_id": "8470001",
        "line": 2.5,
        "candidate_p": 0.60,
        "baseline_p": 0.50,
        "captured_at": "2026-10-08T22:00:00Z",
        "start_time_utc": "2026-10-08T23:00:00Z",
        "role_status": "CONFIRMED",
        "model_version": "shots-v1",
        "source_sha256": SHA,
    }
    row.update(overrides)
    return prediction_from_mapping(row)


def settlement(**overrides):
    row = {
        "market": "PLAYER_SHOTS",
        "game_id": "2026020001",
        "subject_id": "8470001",
        "actual_count": 3,
        "final_at": "2026-10-09T02:00:00Z",
    }
    row.update(overrides)
    value = Settlement(**row)
    value.validate()
    return value


def test_pregame_receipt_joins_to_postgame_settlement():
    rows = join_rows([prediction()], [settlement()])
    assert len(rows) == 1
    assert rows[0].outcome == 1
    assert rows[0].candidate_p == 0.60


def test_at_or_after_puck_drop_prediction_fails_closed():
    with pytest.raises(NHLPropForwardValidationError, match="not pregame"):
        prediction(captured_at="2026-10-08T23:00:00Z")


def test_prediction_outside_frozen_forward_window_fails_closed():
    with pytest.raises(NHLPropForwardValidationError, match="outside frozen forward window"):
        prediction(
            captured_at="2026-10-07T22:00:00Z",
            start_time_utc="2026-10-07T23:00:00Z",
        )


def test_unregistered_line_fails_closed():
    with pytest.raises(NHLPropForwardValidationError, match="outside preregistered grid"):
        prediction(line=5.5)


def test_duplicate_prediction_key_fails_closed():
    row = prediction()
    with pytest.raises(NHLPropForwardValidationError, match="duplicate prediction key"):
        join_rows([row, row], [settlement()])


def test_settlement_must_follow_game_start():
    bad = settlement(final_at="2026-10-08T22:30:00Z")
    with pytest.raises(NHLPropForwardValidationError, match="does not follow game start"):
        join_rows([prediction()], [bad])


def test_projected_rows_are_report_only_and_cannot_satisfy_gate():
    rows = [
        EvaluationRow(
            market="GOALIE_SAVES",
            key=("GOALIE_SAVES", f"g{i}", f"p{i}", 25.5),
            candidate_p=1.0,
            baseline_p=0.5,
            outcome=1,
            role_status="PROJECTED",
        )
        for i in range(100)
    ]
    report = evaluate_market(rows, "GOALIE_SAVES")
    assert report["status"] == "FORWARD_SAMPLE_PENDING"
    assert report["n_confirmed"] == 0
    assert report["n_projected_report_only"] == 100
    assert report["pass"] is False


def test_player_shots_can_pass_only_after_frozen_minimum_and_all_metrics():
    rows = [
        EvaluationRow(
            market="PLAYER_SHOTS",
            key=("PLAYER_SHOTS", f"g{i}", f"p{i}", 2.5),
            candidate_p=1.0,
            baseline_p=0.5,
            outcome=1,
            role_status="CONFIRMED",
        )
        for i in range(200)
    ]
    report = evaluate_market(rows, "PLAYER_SHOTS")
    assert report["n_confirmed"] == 200
    assert report["candidate_brier"] == 0.0
    assert report["baseline_brier"] == 0.25
    assert report["gates"] == {
        "sample_size": True,
        "brier_noninferiority": True,
        "ece": True,
        "absolute_calibration_gap": True,
    }
    assert report["status"] == "PASS_ELIGIBLE_FOR_SEPARATE_PROMOTION_REVIEW"
    assert report["pass"] is True


def test_good_calibration_cannot_pass_before_sample_minimum():
    rows = [
        EvaluationRow(
            market="GOALIE_SAVES",
            key=("GOALIE_SAVES", f"g{i}", f"p{i}", 25.5),
            candidate_p=1.0,
            baseline_p=0.5,
            outcome=1,
            role_status="CONFIRMED",
        )
        for i in range(79)
    ]
    report = evaluate_market(rows, "GOALIE_SAVES")
    assert report["gates"]["sample_size"] is False
    assert report["pass"] is False


def test_candidate_worse_than_baseline_cannot_pass():
    rows = [
        EvaluationRow(
            market="GOALIE_SAVES",
            key=("GOALIE_SAVES", f"g{i}", f"p{i}", 25.5),
            candidate_p=0.0,
            baseline_p=1.0,
            outcome=1,
            role_status="CONFIRMED",
        )
        for i in range(80)
    ]
    report = evaluate_market(rows, "GOALIE_SAVES")
    assert report["gates"]["brier_noninferiority"] is False
    assert report["pass"] is False


def test_source_receipt_requires_real_sha256_shape():
    with pytest.raises(NHLPropForwardValidationError, match="source_sha256"):
        prediction(source_sha256="not-a-sha")
