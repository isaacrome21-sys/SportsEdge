"""CFB live quote verification gate (research-only; SCREEN / NOT_VALIDATED).

A quote may be priced only when BOTH a DraftKings rendered-page quote and an
independent (non-DraftKings, non-DK-derived) price are <= 180s old at pricing
time, neither is captured in the future or at/after kickoff, and both refer to
the same game (home/away team ids + kickoff UTC instant). Anything missing,
malformed or ambiguous fails closed. Passing this gate never sets
play_allowed: promotion is decided separately (ruling 2026-10-23i).

Independent-source status (2026-10-24): no credit-free independent CFB price
source is wired. ESPN scoreboard odds are DraftKings-provided and are rejected
as non-independent; OddsPapi consumes credits. Callers therefore get
INDEPENDENT_PRICE_UNAVAILABLE until a genuinely independent source is added.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

MAX_QUOTE_AGE_SECONDS = 180
DK_RENDERED_SOURCES = frozenset({"DRAFTKINGS_RENDERED_PAGE_V1"})


@dataclass(frozen=True)
class QuoteGateResult:
    ok: bool
    reason: str
    play_allowed: bool = False
    status_label: str = "SCREEN/NOT_VALIDATED"


def _fail(reason: str) -> QuoteGateResult:
    return QuoteGateResult(False, reason)


def _instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def _identity(q: Mapping[str, Any]):
    h, a, ko = q.get("home_team_id"), q.get("away_team_id"), _instant(q.get("kickoff"))
    if h in (None, "") or a in (None, "") or ko is None or str(h) == str(a):
        return None
    return str(h), str(a), ko


def _dk_derived(q: Mapping[str, Any]) -> bool:
    blob = " ".join(str(q.get(k) or "") for k in ("book", "provider", "source")).lower().replace(" ", "")
    return "draftkings" in blob or "dk_" in blob or blob.startswith("dk")


def verify_quote_pair(dk_quote: Optional[Mapping[str, Any]], independent: Optional[Mapping[str, Any]], *,
                      now: datetime) -> QuoteGateResult:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_MUST_BE_TZ_AWARE")
    now = now.astimezone(timezone.utc)
    if not isinstance(dk_quote, Mapping):
        return _fail("DK_QUOTE_UNAVAILABLE")
    if not isinstance(independent, Mapping):
        return _fail("INDEPENDENT_PRICE_UNAVAILABLE")
    if dk_quote.get("source") not in DK_RENDERED_SOURCES:
        return _fail("DK_SOURCE_NOT_RENDERED_PAGE")
    if _dk_derived(independent):
        return _fail("INDEPENDENT_SOURCE_NOT_INDEPENDENT")
    dk_id, ind_id = _identity(dk_quote), _identity(independent)
    if dk_id is None:
        return _fail("DK_GAME_IDENTITY_INVALID")
    if ind_id is None:
        return _fail("INDEPENDENT_GAME_IDENTITY_INVALID")
    if dk_id != ind_id:
        return _fail("GAME_IDENTITY_MISMATCH")
    kickoff = dk_id[2]
    if now >= kickoff:
        return _fail("KICKOFF_PASSED")
    for label, q in (("DK", dk_quote), ("INDEPENDENT", independent)):
        cap = _instant(q.get("captured_at"))
        if cap is None:
            return _fail(f"{label}_CAPTURE_TIME_INVALID")
        if cap > now:
            return _fail(f"{label}_CAPTURE_IN_FUTURE")
        if cap >= kickoff:
            return _fail(f"{label}_CAPTURED_AFTER_KICKOFF")
        if (now - cap).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            return _fail(f"{label}_QUOTE_STALE")
    return QuoteGateResult(True, "QUOTE_PAIR_VERIFIED")
