import pytest

from sportsedge.research.nba_early_season_evidence_join_v1 import join_nba_boxscore_evidence


def fixtures():
    box={"PLAYER_ID":"99","GAME_ID":"ESPN123","TEAM_ABBREVIATION":"NY",
         "SEASON":"2025-26","SEASON_TYPE_ID":"2",
         "MIN":"31:30","PTS":"24","REB":"5","AST":"6"}
    event={"event_id":"ESPN123","tipoff":"2026-01-10T00:30:00Z",
           "result_observed_at":"2026-01-10T05:00:00Z",
           "finalized_at":"2026-01-10T04:50:00Z",
           "event_state":"FINAL","result_state":"FINAL",
           "source_ref":"preserved-event-receipt"}
    role={"player_id":"99","team_abbreviation":"NY","position":"G",
          "observed_at":"2026-01-09T22:00:00Z","source_ref":"roster-receipt"}
    return [box],[event],[role]


def test_join_uses_independently_supplied_event_and_roster_evidence():
    b,e,r=fixtures()
    out=join_nba_boxscore_evidence(b,e,r)
    assert out["joined"]==1
    row=out["rows"][0]
    assert row["game_date"]=="2026-01-09" # 00:30Z is prior Chicago day
    assert row["season"]==2025
    assert row["minutes"]==31.5
    assert row["tipoff"]=="2026-01-10T00:30:00+00:00"
    assert out["receipt_authentication"]=="NOT_ESTABLISHED_BY_CALLER_FIELDS"
    assert out["play_authority"] is False


def test_join_missing_event_receipt_fails_closed():
    b,e,r=fixtures()
    with pytest.raises(ValueError,match="EVENT_RECEIPT_MISSING"):
        join_nba_boxscore_evidence(b,[],r)


def test_join_roster_receipt_after_tip_fails_closed():
    b,e,r=fixtures()
    r[0]["observed_at"]="2026-01-10T01:00:00Z"
    with pytest.raises(ValueError,match="PREGAME_ROLE_RECEIPT_MISSING"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_final_receipt_before_tip_fails_closed():
    b,e,r=fixtures()
    e[0]["result_observed_at"]="2026-01-09T23:50:00Z"
    with pytest.raises(ValueError,match="FINAL_RECEIPT_NOT_AFTER_TIP"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_rejects_ambiguous_season_and_wrong_season():
    b,e,r=fixtures()
    b[0]["SEASON"]="2026"
    with pytest.raises(ValueError,match="SEASON_LABEL_UNVERIFIED"):
        join_nba_boxscore_evidence(b,e,r)
    b[0]["SEASON"]="2026-27"
    with pytest.raises(ValueError,match="SEASON_TIPOFF_INCONSISTENT"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_rejects_duplicate_event_and_player_game():
    b,e,r=fixtures()
    with pytest.raises(ValueError,match="DUPLICATE_EVENT_RECEIPT"):
        join_nba_boxscore_evidence(b,[*e,*e],r)
    with pytest.raises(ValueError,match="DUPLICATE_PLAYER_GAME"):
        join_nba_boxscore_evidence([*b,*b],e,r)


def test_join_nonregular_excluded_not_treated_as_prior():
    b,e,r=fixtures()
    b[0]["SEASON_TYPE_ID"]="3"
    out=join_nba_boxscore_evidence(b,e,r)
    assert out["joined"]==0
    assert out["skipped_non_regular"]==1


def test_join_invalid_minutes_and_stats_refuse():
    b,e,r=fixtures()
    b[0]["MIN"]="30:99"
    with pytest.raises(ValueError,match="MINUTES_INVALID"):
        join_nba_boxscore_evidence(b,e,r)
    b[0]["MIN"]="30:00"
    b[0]["REB"]="-1"
    with pytest.raises(ValueError,match="REB_INVALID"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_requires_explicit_final_state_not_merely_post_tip_receipt():
    b,e,r=fixtures()
    e[0]["result_observed_at"]="2026-01-10T00:30:01Z"
    e[0]["finalized_at"]="2026-01-10T00:30:01Z"
    del e[0]["event_state"]
    with pytest.raises(ValueError,match="FINAL_STATE_WITNESS_MISSING"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_rejects_result_receipt_before_finalization():
    b,e,r=fixtures()
    e[0]["finalized_at"]="2026-01-10T05:01:00Z"
    with pytest.raises(ValueError,match="FINAL_STATE_CHRONOLOGY_INVALID"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_rejects_claimed_finalization_before_tipoff():
    b,e,r=fixtures()
    e[0]["finalized_at"]="2026-01-10T00:29:59Z"
    with pytest.raises(ValueError,match="FINAL_STATE_CHRONOLOGY_INVALID"):
        join_nba_boxscore_evidence(b,e,r)


def test_join_uses_chicago_local_date_for_season_membership():
    b,e,r=fixtures()
    # 2026-10-01 00:30 UTC is Sep 30 19:30 Chicago, outside
    # the 2026-27 regular season even though UTC month is October.
    b[0]["SEASON"]="2026-27"
    e[0]["tipoff"]="2026-10-01T00:30:00Z"
    e[0]["finalized_at"]="2026-10-01T04:50:00Z"
    e[0]["result_observed_at"]="2026-10-01T05:00:00Z"
    r[0]["observed_at"]="2026-09-30T22:00:00Z"
    with pytest.raises(ValueError,match="SEASON_TIPOFF_INCONSISTENT"):
        join_nba_boxscore_evidence(b,e,r)


def test_valid_join_preserves_final_receipt_and_role_witness_for_audit():
    b,e,r=fixtures()
    row=join_nba_boxscore_evidence(b,e,r)["rows"][0]
    assert row["event_state"]=="FINAL"
    assert row["result_state"]=="FINAL"
    assert row["finalized_at"]=="2026-01-10T04:50:00+00:00"
    assert row["observed_at"]=="2026-01-10T05:00:00+00:00"
    assert row["role_observed_at"]=="2026-01-09T22:00:00+00:00"
    assert row["role_source_ref"]=="roster-receipt"
    assert row["receipt_authentication"]=="NOT_ESTABLISHED_BY_CALLER_FIELDS"


def test_newer_pretip_role_receipt_supersedes_older_position():
    b,e,r=fixtures()
    r.insert(0, {
        "player_id":"99", "team_abbreviation":"NY", "position":"G",
        "observed_at":"2026-01-09T18:00:00Z",
        "source_ref":"older-roster-receipt",
    })
    r[1]["position"]="F"
    row=join_nba_boxscore_evidence(b,e,r)["rows"][0]
    assert row["position"]=="F"
    assert row["role_observed_at"]=="2026-01-09T22:00:00+00:00"
    assert row["role_source_ref"]=="roster-receipt"


def test_same_latest_instant_conflicting_role_evidence_fails_closed():
    b,e,r=fixtures()
    r.append({
        "player_id":"99", "team_abbreviation":"NY", "position":"F",
        "observed_at":"2026-01-09T22:00:00Z",
        "source_ref":"conflicting-roster-receipt",
    })
    with pytest.raises(ValueError,match="AMBIGUOUS_LATEST_PLAYER_ROLE"):
        join_nba_boxscore_evidence(b,e,r)
