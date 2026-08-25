"""Shared fail-closed run/acquisition/engine/decision state semantics.

This module is sport-agnostic by design. Football and MLB must not invent
separate interpretations of READY/PASS/BLOCKED.  It also defines the minimal
contract for an externally observed evidence heartbeat so an Actions-hosted
scheduler cannot certify its own liveness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

RUN_STATES = frozenset({"READY", "DEGRADED", "BLOCKED"})
ACQUISITION_STATES = frozenset({"OFFERED", "NOT_OFFERED", "ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"})
ENGINE_STATES = frozenset({"PRICED", "NO_ENGINE", "INPUT_MISSING", "ENGINE_BLOCKED"})
DECISION_STATES = frozenset({"BET", "PASS"})
CARD_STATES = frozenset({"BETS_FOUND", "NO_BETS"})


@dataclass(frozen=True)
class SlotState:
    game_id: str
    market: str
    acquisition: str
    engine: str
    decision: str | None


@dataclass(frozen=True)
class RunSummary:
    run_status: str
    card_status: str
    total_slots: int
    offered_slots: int
    priced_slots: int
    bet_slots: int
    blocker_count: int


@dataclass(frozen=True)
class ExternalHeartbeat:
    observer: str
    observed_at: str
    age_seconds: float
    max_age_seconds: float
    fresh: bool
    status: str


def classify_acquisition(*, provider_supported: bool, request_succeeded: bool, offer_found: bool) -> str:
    """Classify provider acquisition without collapsing missing into not offered."""
    if not provider_supported:
        return "PROVIDER_UNSUPPORTED"
    if not request_succeeded:
        return "ACQUISITION_MISSING"
    return "OFFERED" if offer_found else "NOT_OFFERED"


def validate_slot_state(slot: SlotState) -> SlotState:
    if slot.acquisition not in ACQUISITION_STATES:
        raise ValueError(f"INVALID_ACQUISITION_STATE:{slot.acquisition}")
    if slot.engine not in ENGINE_STATES:
        raise ValueError(f"INVALID_ENGINE_STATE:{slot.engine}")
    if slot.decision is not None and slot.decision not in DECISION_STATES:
        raise ValueError(f"INVALID_DECISION_STATE:{slot.decision}")
    if slot.decision is not None and not (slot.acquisition == "OFFERED" and slot.engine == "PRICED"):
        raise ValueError("DECISION_REQUIRES_PRICED_OFFER")
    if not str(slot.game_id).strip():
        raise ValueError("GAME_ID_REQUIRED")
    if not str(slot.market).strip():
        raise ValueError("MARKET_REQUIRED")
    return slot


def _slot_is_blocked(slot: SlotState) -> bool:
    if slot.acquisition == "ACQUISITION_MISSING":
        return True
    if slot.acquisition == "OFFERED" and slot.engine in {"NO_ENGINE", "INPUT_MISSING", "ENGINE_BLOCKED"}:
        return True
    return False


def summarize_run(slots: Iterable[SlotState]) -> RunSummary:
    rows = [validate_slot_state(slot) for slot in slots]
    if not rows:
        return RunSummary("BLOCKED", "NO_BETS", 0, 0, 0, 0, 1)

    offered = sum(slot.acquisition == "OFFERED" for slot in rows)
    priced = sum(slot.acquisition == "OFFERED" and slot.engine == "PRICED" for slot in rows)
    bets = sum(slot.decision == "BET" for slot in rows)
    blockers = sum(_slot_is_blocked(slot) for slot in rows)

    # A run with actual blocked slots and nothing priceable can never self-label
    # READY.  Partial success is DEGRADED.  Known NOT_OFFERED and
    # PROVIDER_UNSUPPORTED states are not acquisition failures and therefore do
    # not degrade an otherwise healthy run.
    if blockers and priced == 0:
        run_status = "BLOCKED"
    elif blockers:
        run_status = "DEGRADED"
    else:
        run_status = "READY"

    card_status = "BETS_FOUND" if bets else "NO_BETS"
    return RunSummary(
        run_status=run_status,
        card_status=card_status,
        total_slots=len(rows),
        offered_slots=offered,
        priced_slots=priced,
        bet_slots=bets,
        blocker_count=blockers,
    )


def _utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name}_MUST_BE_DATETIME")
    if value.tzinfo is None:
        raise ValueError(f"{name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def evaluate_external_heartbeat(
    *,
    observer: str,
    observed_at: datetime,
    now: datetime,
    max_age: timedelta,
) -> ExternalHeartbeat:
    """Evaluate liveness only from an observer outside GitHub Actions.

    An Actions job cannot be the sole witness that Actions scheduling is alive.
    This function therefore rejects self-observers explicitly and records a
    machine-readable fresh/stale result for a genuinely external checker.
    """
    normalized = str(observer).strip().lower().replace("_", "-")
    if not normalized or normalized in {"actions", "github-actions", "githubactions", "gha"}:
        raise ValueError("EXTERNAL_OBSERVER_REQUIRED")
    if not isinstance(max_age, timedelta) or max_age.total_seconds() <= 0:
        raise ValueError("POSITIVE_MAX_AGE_REQUIRED")
    observed = _utc(observed_at, name="OBSERVED_AT")
    current = _utc(now, name="NOW")
    age = (current - observed).total_seconds()
    if age < 0:
        raise ValueError("HEARTBEAT_FROM_FUTURE")
    fresh = age <= max_age.total_seconds()
    return ExternalHeartbeat(
        observer=str(observer).strip(),
        observed_at=observed.isoformat(),
        age_seconds=age,
        max_age_seconds=max_age.total_seconds(),
        fresh=fresh,
        status="EXTERNAL_HEARTBEAT_FRESH" if fresh else "EXTERNAL_HEARTBEAT_STALE",
    )
