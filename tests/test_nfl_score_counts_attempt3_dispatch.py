import json
from pathlib import Path

from scripts.run_nfl_score_counts_attempt import code_identity, sha256_file

MARKER = Path("config/research/nfl_score_counts_attempt3_dispatch_v1.json")
PREREG = Path("config/research/nfl_score_counts_g1_attempt3_fg_prereg_v1.json")
ATTEMPT2 = Path("config/research/nfl_score_counts_g1_attempt2_result_v1.json")


def test_attempt3_dispatch_marker_is_exact_hash_bound_and_research_only():
    x = json.loads(MARKER.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT3_DISPATCH_V1"
    assert x["status"] == "ARMED_SINGLE_MAIN_PUSH"
    assert x["candidate_family"] == "NFL_SCORE_COUNTS_G1"
    assert x["attempt_number"] == 3
    assert x["confirmation"] == "CONSUME_SCORE_COUNTS_ATTEMPT_3"
    assert x["prereg_sha256"] == sha256_file(PREREG)
    assert x["attempt_2_result_sha256"] == sha256_file(ATTEMPT2)
    assert x["code_identity"] == code_identity()
    assert x["rules"]["attempt_1_result_preserved"] is True
    assert x["rules"]["attempt_2_result_preserved"] is True
    assert x["rules"]["thresholds_unchanged"] is True
    assert x["rules"]["no_fourth_attempt"] is True
    assert x["rules"]["backfill"] is False
    assert x["rules"]["market_data_for_model_fit"] is False
    assert x["rules"]["source_substitution"] is False
    assert x["authority"]["creates_model_p"] is False
    assert x["authority"]["official"] is False
