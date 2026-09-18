"""Prospective EV_TRACKER_POLICY_V3 acquisition-health state machine.

No result, CLV, ROI, or grading input is accepted. Recovery observations are NOT_EVIDENCE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

ACTIVE = "ACTIVE"
SUSPENDED = "SUSPENDED"
RECOVERING = "RECOVERING"
NOT_EVIDENCE = "NOT_EVIDENCE"

PROVIDER_FAILURES = {
    "ODDS_API_UNAUTHORIZED", "ODDS_API_FORBIDDEN", "ODDS_API_HTTP_5XX",
    "ODDS_API_UNREACHABLE", "ODDS_API_TIMEOUT",
}
NON_OUTAGES = {"BUDGET_RESERVE_REACHED", "CREDITS_EXHAUSTED", "MANUAL_MISSED", "USER_DELAY"}

@dataclass(frozen=True)
class State:
    name: str = ACTIVE
    recovery_streak: int = 0


def _dt(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("ATTEMPT_TIME_INVALID")
    return dt.astimezone(timezone.utc)


def provider_outage(attempts: Iterable[Mapping], *, configured_slots: int,
                    bounded_window_minutes: int = 30, min_distinct_events: int = 2,
                    lane_type: str = "AUTOMATED_PROVIDER") -> bool:
    """True only for machine-observed provider-class failure; manual/budget failures never qualify."""
    if lane_type != "AUTOMATED_PROVIDER" or configured_slots < 1:
        return False
    rows = list(attempts)
    if not rows:
        return False
    qualifying = [r for r in rows if r.get("error_code") in PROVIDER_FAILURES]
    if len(qualifying) != len(rows):
        return False
    times = [_dt(str(r["attempted_at"])) for r in qualifying]
    if max(times) - min(times) > timedelta(minutes=bounded_window_minutes):
        return False
    events = {str(r.get("event_id") or "") for r in qualifying if r.get("event_id")}
    slots = {str(r.get("credential_slot") or "") for r in qualifying if r.get("credential_slot")}
    return len(events) >= min_distinct_events and len(slots) == configured_slots


def transition(state: State, *, outage: bool = False, recovery_slate_success: bool | None = None,
               recovery_k: int = 3) -> State:
    if recovery_k < 1:
        raise ValueError("RECOVERY_K_INVALID")
    if state.name == ACTIVE:
        return State(SUSPENDED, 0) if outage else state
    if state.name == SUSPENDED:
        if recovery_slate_success is None:
            return state
        return State(RECOVERING, 1) if recovery_slate_success else state
    if state.name == RECOVERING:
        if recovery_slate_success is None:
            return state
        if not recovery_slate_success:
            return State(SUSPENDED, 0)
        streak = state.recovery_streak + 1
        return State(ACTIVE, 0) if streak >= recovery_k else State(RECOVERING, streak)
    raise ValueError("STATE_INVALID")


def admission_disposition(state: State) -> str:
    return "EVIDENCE_ALLOWED" if state.name == ACTIVE else NOT_EVIDENCE


def credential_health(*, remaining_credits: int | None, error_codes: Iterable[str]) -> str:
    codes = set(error_codes)
    if "ODDS_API_UNAUTHORIZED" in codes or "ODDS_API_FORBIDDEN" in codes:
        return "DEGRADED_CREDENTIAL"
    if remaining_credits is not None and remaining_credits <= 0:
        return "DEGRADED_ZERO_CREDITS"
    return "HEALTHY"
