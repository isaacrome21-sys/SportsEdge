"""Hard spend and reserve controls for paid sportsbook acquisition.

The ledger records actual provider cost when headers are available and is written
atomically. Callers can enforce both a local daily cap and a provider-account
reserve. Unknown provider balance fails closed whenever a positive reserve is
required; this prevents scheduled jobs from silently draining a quota that has
not been reconciled.
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
    provider_credits_remaining: int | None = None
    provider_credits_used: int | None = None

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
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OddsBudgetError("ODDS_BUDGET_LEDGER_INVALID") from exc
    if not isinstance(raw, Mapping):
        raise OddsBudgetError("ODDS_BUDGET_LEDGER_INVALID")
    if str(raw.get("date_utc")) != date_utc:
        return BudgetState(date_utc=date_utc, cap_credits=int(cap_credits), consumed_credits=0)
    try:
        consumed = int(raw.get("consumed_credits", 0))
    except (TypeError, ValueError) as exc:
        raise OddsBudgetError("ODDS_BUDGET_LEDGER_INVALID") from exc
    if consumed < 0:
        raise OddsBudgetError("ODDS_BUDGET_LEDGER_INVALID")
    return BudgetState(
        date_utc=date_utc,
        cap_credits=int(cap_credits),
        consumed_credits=consumed,
        provider_credits_remaining=_optional_nonnegative_int(raw.get("provider_credits_remaining")),
        provider_credits_used=_optional_nonnegative_int(raw.get("provider_credits_used")),
    )


def assert_budget_available(
    state: BudgetState,
    *,
    estimated_cost: int,
    reserve_credits: int = 0,
    provider_credits_remaining: int | None = None,
) -> None:
    cost = max(0, int(estimated_cost))
    reserve = int(reserve_credits)
    if reserve < 0:
        raise OddsBudgetError("ODDS_PROVIDER_RESERVE_INVALID")
    if state.consumed_credits + cost > state.cap_credits:
        raise OddsBudgetError(
            f"BLOCKED_BUDGET:consumed={state.consumed_credits}:estimated={cost}:cap={state.cap_credits}"
        )
    provider_remaining = (
        state.provider_credits_remaining
        if provider_credits_remaining is None
        else _optional_nonnegative_int(provider_credits_remaining)
    )
    if reserve > 0 and provider_remaining is None:
        raise OddsBudgetError(
            f"BLOCKED_PROVIDER_BALANCE_UNKNOWN:estimated={cost}:reserve={reserve}"
        )
    if provider_remaining is not None and provider_remaining - cost < reserve:
        raise OddsBudgetError(
            "BLOCKED_PROVIDER_RESERVE:"
            f"remaining={provider_remaining}:estimated={cost}:reserve={reserve}"
        )


def record_actual_cost(
    path: str | Path,
    *,
    state: BudgetState,
    actual_cost: int,
    provider_headers: Mapping[str, Any] | None = None,
) -> BudgetState:
    actual = max(0, int(actual_cost))
    header_remaining = _header_int(provider_headers, "x-requests-remaining")
    header_used = _header_int(provider_headers, "x-requests-used")
    updated = BudgetState(
        date_utc=state.date_utc,
        cap_credits=state.cap_credits,
        consumed_credits=state.consumed_credits + actual,
        provider_credits_remaining=(header_remaining if header_remaining is not None else state.provider_credits_remaining),
        provider_credits_used=header_used if header_used is not None else state.provider_credits_used,
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date_utc": updated.date_utc,
        "cap_credits": updated.cap_credits,
        "consumed_credits": updated.consumed_credits,
        "remaining_credits": updated.remaining_credits,
        "provider_credits_remaining": updated.provider_credits_remaining,
        "provider_credits_used": updated.provider_credits_used,
        "last_call_cost": actual,
    }
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)
    return updated


def provider_last_call_cost(headers: Mapping[str, Any] | None, *, fallback: int) -> int:
    value = _header_int(headers, "x-requests-last")
    return max(0, int(fallback if value is None else value))


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
            value = headers.get(key)
        except Exception:
            value = None
    return _optional_nonnegative_int(value)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        out = int(str(value))
    except Exception:
        return None
    return out if out >= 0 else None
