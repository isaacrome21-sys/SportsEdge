"""Hard daily spend controls for paid sportsbook acquisition.

The ledger is deliberately tiny and append-safe. It records actual provider cost
from response headers, not estimated cost, and refuses further paid calls once the
daily cap would be exceeded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


class OddsBudgetError(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetState:
    date_utc: str
    cap_credits: int
    consumed_credits: int

    @property
    def remaining_credits(self) -> int:
        return max(0, self.cap_credits - self.consumed_credits)


def _today_utc(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()


def load_budget(path: str | Path, *, cap_credits: int, now: datetime | None = None) -> BudgetState:
    if int(cap_credits) <= 0:
        raise OddsBudgetError("ODDS_DAILY_BUDGET_INVALID")
    date_utc = _today_utc(now)
    p = Path(path)
    if not p.exists():
        return BudgetState(date_utc=date_utc, cap_credits=int(cap_credits), consumed_credits=0)
    try:
        raw = json.loads(p.read_text())
    except Exception as exc:
        raise OddsBudgetError("ODDS_BUDGET_LEDGER_INVALID") from exc
    if str(raw.get("date_utc")) != date_utc:
        return BudgetState(date_utc=date_utc, cap_credits=int(cap_credits), consumed_credits=0)
    consumed = int(raw.get("consumed_credits", 0))
    return BudgetState(date_utc=date_utc, cap_credits=int(cap_credits), consumed_credits=max(0, consumed))


def assert_budget_available(state: BudgetState, *, estimated_cost: int) -> None:
    cost = max(0, int(estimated_cost))
    if state.consumed_credits + cost > state.cap_credits:
        raise OddsBudgetError(
            f"BLOCKED_BUDGET:consumed={state.consumed_credits}:estimated={cost}:cap={state.cap_credits}"
        )


def record_actual_cost(
    path: str | Path,
    *,
    state: BudgetState,
    actual_cost: int,
    provider_headers: Mapping[str, Any] | None = None,
) -> BudgetState:
    actual = max(0, int(actual_cost))
    updated = BudgetState(
        date_utc=state.date_utc,
        cap_credits=state.cap_credits,
        consumed_credits=state.consumed_credits + actual,
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date_utc": updated.date_utc,
        "cap_credits": updated.cap_credits,
        "consumed_credits": updated.consumed_credits,
        "remaining_credits": updated.remaining_credits,
        "provider_credits_remaining": _header_int(provider_headers, "x-requests-remaining"),
        "provider_credits_used": _header_int(provider_headers, "x-requests-used"),
        "last_call_cost": actual,
    }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return updated


def _header_int(headers: Mapping[str, Any] | None, key: str) -> int | None:
    if not headers:
        return None
    value = None
    for candidate in (key, key.lower(), key.upper()):
        if candidate in headers:
            value = headers[candidate]
            break
    if value is None:
        try:
            value = headers.get(key)  # type: ignore[attr-defined]
        except Exception:
            value = None
    try:
        return int(str(value)) if value is not None else None
    except Exception:
        return None
