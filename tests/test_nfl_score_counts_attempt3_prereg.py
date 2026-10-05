import json
from pathlib import Path


def test_attempt2_result_is_permanent_failed_consumed_record():
    row = json.loads(Path(
        "config/research/nfl_score_counts_g1_attempt2_result_v1.json"
    ).read_text())
    assert row["attempt_number"] == 2
    assert row["attempt_consumed"] is True
    assert row["status"] == "DEVELOPMENT_ATTEMPT_FAIL"
    assert row["artifact_self_digest_verified"] is True
    assert row["development_gate"]["touchdowns"]["fold_wins"] == 5
    assert row["development_gate"]["made_field_goals"]["fold_wins"] == 2
    assert row["development_gate"]["made_field_goals"]["pass"] is False
    assert row["attempt_accounting"]["remaining_after_attempt"] == 1


def test_attempt3_prereg_is_frozen_before_implementation():
    row = json.loads(Path(
        "config/research/nfl_score_counts_g1_attempt3_fg_prereg_v1.json"
    ).read_text())
    assert row["attempt_number"] == 3
    assert row["status"] == "FROZEN_BEFORE_ATTEMPT_3_IMPLEMENTATION_OR_SCORING"
    assert row["attempt_budget"]["consumed_before_this_attempt"] == 2
    assert row["attempt_budget"]["remaining_before_this_attempt"] == 1
    assert row["reason"]["touchdown_model_change"] is False
    assert row["field_goal_attempt_3_spec"]["family"] == (
        "THINNED_POISSON_OPPORTUNITY_X_CONVERSION"
    )
    assert row["field_goal_attempt_3_spec"]["opportunity_target"] == (
        "FIELD_GOAL_ATTEMPTS"
    )
    assert row["preserved_components"]["minimum_fold_wins_each"] == 3
    assert row["execution_rules"]["no_fourth_attempt"] is True
