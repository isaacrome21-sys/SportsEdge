import json
from pathlib import Path

RESULT = Path("config/research/nfl_score_counts_g1_attempt3_result_v1.json")


def test_attempt3_failure_is_permanent_and_exhausts_g1_budget():
    x = json.loads(RESULT.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT3_RESULT_V1"
    assert x["status"] == "DEVELOPMENT_ATTEMPT_FAIL"
    assert x["candidate_family"] == "NFL_SCORE_COUNTS_G1"
    assert x["attempt_number"] == 3
    assert x["attempt_consumed"] is True
    assert x["workflow_run_id"] == 37381125793
    assert x["artifact_id"] == 11378891102
    assert x["artifact_archive_sha256"] == "2a147d0b4f497cdddbf08a0958cbe635f5c4356e003826738d2902620ebba37c"
    assert x["fit_file_sha256"] == "6267e4ef44aba5b799a492ea4bd9cf3ac30fac4cedb2a72e0de0a9535e9cbba6"
    assert x["fit_artifact_sha256"] == "f7b6237f343fb036c86152502c20f770125c9e627cdf1c3b755ffce97389a306"
    assert x["artifact_self_digest_verified"] is True
    assert x["development_gate"]["pass"] is False
    assert x["development_gate"]["offense_touchdowns"]["pass"] is True
    assert x["development_gate"]["offense_touchdowns"]["fold_wins"] == 5
    assert x["development_gate"]["made_field_goals"]["pass"] is False
    assert x["development_gate"]["made_field_goals"]["fold_wins"] == 2
    assert x["development_gate"]["made_field_goals"]["winning_validation_seasons"] == [2021, 2025]
    assert x["attempt_accounting"]["maximum"] == 3
    assert x["attempt_accounting"]["consumed_after_attempt"] == 3
    assert x["attempt_accounting"]["remaining_after_attempt"] == 0
    assert x["attempt_accounting"]["next_attempt"] is None
    assert x["attempt_accounting"]["candidate_family_exhausted"] is True
    assert x["rules"]["no_fourth_attempt"] is True
    assert x["authority"]["creates_model_p"] is False
    assert x["authority"]["official"] is False
