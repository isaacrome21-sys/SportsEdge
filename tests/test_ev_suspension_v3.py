from sportsedge.ev_suspension_v3 import (
    ACTIVE, SUSPENDED, RECOVERING, NOT_EVIDENCE, State,
    admission_disposition, credential_health, provider_outage, transition,
)


def attempt(event, slot, code, at="2026-09-17T01:00:00Z"):
    return {"event_id": event, "credential_slot": slot, "error_code": code, "attempted_at": at}


def test_budget_exhaustion_does_not_suspend():
    rows = [attempt("a", "1", "BUDGET_RESERVE_REACHED"), attempt("b", "2", "BUDGET_RESERVE_REACHED")]
    assert provider_outage(rows, configured_slots=2) is False
    assert transition(State(), outage=False).name == ACTIVE


def test_manual_lane_cannot_suspend_even_on_401():
    rows = [attempt("a", "1", "ODDS_API_UNAUTHORIZED"), attempt("b", "2", "ODDS_API_UNAUTHORIZED")]
    assert provider_outage(rows, configured_slots=2, lane_type="MANUAL") is False


def test_provider_wide_401_can_suspend_when_all_slots_and_events_fail():
    rows = [
        attempt("a", "1", "ODDS_API_UNAUTHORIZED"), attempt("a", "2", "ODDS_API_UNAUTHORIZED"),
        attempt("b", "1", "ODDS_API_UNAUTHORIZED"), attempt("b", "2", "ODDS_API_UNAUTHORIZED"),
    ]
    assert provider_outage(rows, configured_slots=2)
    assert transition(State(), outage=True).name == SUSPENDED


def test_suspended_lane_refuses_evidence_admission():
    assert admission_disposition(State(SUSPENDED)) == NOT_EVIDENCE
    assert admission_disposition(State(RECOVERING, 2)) == NOT_EVIDENCE


def test_three_clean_recovery_slates_required_and_are_not_evidence():
    s = State(SUSPENDED)
    s = transition(s, recovery_slate_success=True, recovery_k=3)
    assert s == State(RECOVERING, 1) and admission_disposition(s) == NOT_EVIDENCE
    s = transition(s, recovery_slate_success=True, recovery_k=3)
    assert s == State(RECOVERING, 2) and admission_disposition(s) == NOT_EVIDENCE
    s = transition(s, recovery_slate_success=True, recovery_k=3)
    assert s == State(ACTIVE, 0)


def test_recovery_failure_returns_to_suspended():
    assert transition(State(RECOVERING, 2), recovery_slate_success=False) == State(SUSPENDED, 0)


def test_zero_credits_and_401_are_never_green():
    assert credential_health(remaining_credits=0, error_codes=[]) == "DEGRADED_ZERO_CREDITS"
    assert credential_health(remaining_credits=100, error_codes=["ODDS_API_UNAUTHORIZED"]) == "DEGRADED_CREDENTIAL"


def test_pre_suspension_miss_has_no_reclassification_api():
    # The state machine consumes attempt health only and exposes no ledger mutation/delete operation.
    miss = {"disposition": "MISSED", "policy_id": "EV_TRACKER_POLICY_V2", "content_sha256": "abc"}
    before = dict(miss)
    transition(State(), outage=True)
    assert miss == before
