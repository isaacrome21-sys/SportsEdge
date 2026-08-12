"""Shadow-only wager execution adapter.

This module deliberately contains no sportsbook HTTP implementation. It exercises
the exact reservation lifecycle future production placement must use while the
actual placement call is supplied as a local/test stub.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .execution_reservation import (
    ExecutionReservationError,
    archive_finalized_reservation,
    finalize_reservation,
    reserve_wager,
)


class ShadowExecutionError(RuntimeError):
    pass


def execute_shadow(
    decision: Mapping[str, Any],
    root: str | Path,
    *,
    placement_stub: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exercise reserve -> attempt -> finalize -> archive with no real placement.

    The callback runs only after the atomic reservation exists. A successful
    shadow attempt is RELEASED (never PLACED) so it cannot be confused with a
    real sportsbook wager. Failed/rejected attempts are archived as FAILED.
    """
    if decision.get("execution_ready") is not True:
        raise ShadowExecutionError("DECISION_NOT_EXECUTION_READY")
    if not callable(placement_stub):
        raise ShadowExecutionError("PLACEMENT_STUB_REQUIRED")

    try:
        reserved = reserve_wager(decision, root, now=now)
    except ExecutionReservationError as exc:
        raise ShadowExecutionError(str(exc)) from exc

    wager_key = str(reserved["wager_key"])
    try:
        result = placement_stub(dict(decision))
        if not isinstance(result, Mapping):
            raise ShadowExecutionError("SHADOW_RESULT_NOT_MAPPING")
        accepted = result.get("accepted")
        if accepted is not True:
            detail = str(result.get("reason") or "SHADOW_REJECTED")
            finalize_reservation(root, wager_key, status="FAILED", now=now, detail=detail)
            archive = archive_finalized_reservation(root, wager_key, now=now)
            return {
                "execution_mode": "SHADOW",
                "status": "FAILED",
                "wager_key": wager_key,
                "decision_id": decision.get("decision_id"),
                "detail": detail,
                "reservation_archive": str(archive),
            }

        detail = str(result.get("reason") or "SHADOW_ACCEPTED")
        finalize_reservation(root, wager_key, status="RELEASED", now=now, detail=detail)
        archive = archive_finalized_reservation(root, wager_key, now=now)
        return {
            "execution_mode": "SHADOW",
            "status": "RELEASED",
            "wager_key": wager_key,
            "decision_id": decision.get("decision_id"),
            "detail": detail,
            "reservation_archive": str(archive),
        }
    except Exception as exc:
        try:
            finalize_reservation(root, wager_key, status="FAILED", now=now, detail=f"SHADOW_EXCEPTION:{type(exc).__name__}")
            archive_finalized_reservation(root, wager_key, now=now)
        except Exception:
            # Preserve the original failure; any remaining RESERVED file is then
            # handled only by explicit stale-reservation recovery.
            pass
        if isinstance(exc, ShadowExecutionError):
            raise
        raise ShadowExecutionError(f"SHADOW_PLACEMENT_EXCEPTION:{type(exc).__name__}") from exc
