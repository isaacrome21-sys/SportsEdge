import json
from pathlib import Path

MARKER = Path("config/research/nfl_score_counts_attempt2_dispatch_v1.json")
WORKFLOW = Path(".github/workflows/nfl-score-counts-attempt2-main-trigger.yml")
PREREG = Path("config/research/nfl_score_counts_g1_attempt2_fg_prereg_v1.json")


def test_attempt2_prereg_is_fg_only_and_preserves_gate():
    x = json.loads(PREREG.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT2_FG_PREREG_V1"
    assert x["status"] == "FROZEN_BEFORE_ATTEMPT_2_IMPLEMENTATION_OR_SCORING"
    assert x["attempt_number"] == 2
    assert x["reason"]["change_scope"] == "FIELD_GOAL_MEAN_MODEL_ONLY"
    assert x["reason"]["touchdown_model_change"] is False
    assert x["field_goal_attempt_2_spec"]["feature_names"] == [
        "made_fg_per_game",
        "opp_fg_allowed_per_game",
        "off_plays_per_game",
        "home_indicator",
    ]
    assert x["field_goal_attempt_2_spec"]["alpha_grid"] == [0.1, 1.0, 10.0, 100.0, 1000.0]
    assert x["preserved_components"]["all_targets_must_pass"] is True
    assert x["preserved_components"]["minimum_fold_wins_each"] == 3
    assert x["preserved_components"]["backfill"] is False


def test_attempt2_marker_is_exact_and_research_only():
    x = json.loads(MARKER.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT2_DISPATCH_V1"
    assert x["status"] == "ARMED_SINGLE_MAIN_PUSH"
    assert x["attempt_number"] == 2
    assert x["confirmation"] == "CONSUME_SCORE_COUNTS_ATTEMPT_2"
    assert x["rules"]["attempt_1_result_preserved"] is True
    assert x["rules"]["thresholds_unchanged"] is True
    assert x["rules"]["backfill"] is False
    assert x["authority"]["creates_model_p"] is False
    assert x["authority"]["official"] is False


def test_attempt2_trigger_is_main_push_marker_scoped_not_pr_scoped():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "nfl_score_counts_attempt2_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "--attempt-number 2" in text
    assert "--confirm CONSUME_SCORE_COUNTS_ATTEMPT_2" in text
