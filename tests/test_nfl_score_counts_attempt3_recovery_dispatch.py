import json
from pathlib import Path

from scripts.run_nfl_score_counts_attempt import sha256_file

MARKER = Path("config/research/nfl_score_counts_attempt3_recovery_dispatch_v1.json")
ORIGINAL = Path("config/research/nfl_score_counts_attempt3_dispatch_v1.json")


def test_attempt3_recovery_marker_reuses_original_authorization_without_new_attempt():
    x = json.loads(MARKER.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT3_RECOVERY_DISPATCH_V1"
    assert x["status"] == "ARMED_RECOVERY_MAIN_PUSH"
    assert x["candidate_family"] == "NFL_SCORE_COUNTS_G1"
    assert x["attempt_number"] == 3
    assert x["confirmation"] == "CONSUME_SCORE_COUNTS_ATTEMPT_3"
    assert x["original_dispatch_sha256"] == sha256_file(ORIGINAL)
    assert x["reason"] == "ORIGINAL_DISPATCH_MERGED_BEFORE_TRIGGER_WORKFLOW_EXISTED"
    assert x["rules"]["original_authorization_preserved"] is True
    assert x["rules"]["recovery_is_not_a_new_attempt"] is True
    assert x["rules"]["thresholds_unchanged"] is True
    assert x["rules"]["no_fourth_attempt"] is True
    assert x["rules"]["backfill"] is False
    assert x["rules"]["market_data_for_model_fit"] is False
    assert x["rules"]["source_substitution"] is False
    assert x["authority"]["research_only"] is True
    assert x["authority"]["creates_model_p"] is False
