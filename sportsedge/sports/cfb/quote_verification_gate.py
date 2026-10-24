"""CFB live quote verification gate (research-only; SCREEN / NOT_VALIDATED).

A quote may be priced only when BOTH a DraftKings rendered-page quote and an
independent price satisfy every rule below; anything missing, malformed or
ambiguous fails closed. Passing never sets play_allowed (promotion is decided
separately under ruling 2026-10-23i).

* Independent source: must be on an explicit ALLOWLIST of known-independent,
  non-DraftKings-derived sources. ESPN (any label, incl. ESPN BET / scoreboard,
  which are DraftKings-provided) and any DraftKings spelling are refused even
  if allowlisted. Each of source/book/provider is checked separately.
* Freshness: age <= MAX_QUOTE_AGE_SECONDS (180s, INCLUSIVE) at pricing time;
  no capture in the future or at/after kickoff.
* Identity: same home/away team ids (strings, type-strict) and the same
  kickoff UTC instant; same market, side and line; valid American odds.

Independent-source status (2026-10-24): the production allowlist is EMPTY --
no credit-free independent CFB price source is wired -- so every quote returns
INDEPENDENT_PRICE_UNAVAILABLE.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, FrozenSet, Mapping, Optional

MAX_QUOTE_AGE_SECONDS = 180  # inclusive: age == 180s passes, 181s fails
DK_RENDERED_SOURCES = frozenset({"DRAFTKINGS_RENDERED_PAGE_V1"})
INDEPENDENT_SOURCE_ALLOWLIST: FrozenSet[str] = frozenset()
MARKETS = {"SPREAD": {"HOME", "AWAY"}, "TOTAL": {"OVER", "UNDER"}, "ML": {"HOME", "AWAY"}}
_LABEL_FIELDS = ("source", "book", "provider")


@dataclass(frozen=True)
class QuoteGateResult:
    ok: bool
    reason: str
    play_allowed: bool = False
    status_label: str = "SCREEN/NOT_VALIDATED"


def _fail(reason: str) -> QuoteGateResult:
    return QuoteGateResult(False, reason)


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower()) if isinstance(v, str) else ""


def _is_dk_label(n: str) -> bool:
    return ("draftkings" in n or "draftking" in n or n.startswith("dk") or n.endswith("dk")
            or "dkng" in n or "dksportsbook" in n)


def _is_espn_label(n: str) -> bool:
    return "espn" in n


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


def _team(v: Any) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _identity(q: Mapping[str, Any]):
    h, a, ko = _team(q.get("home_team_id")), _team(q.get("away_team_id")), _instant(q.get("kickoff"))
    if h is None or a is None or ko is None or h == a:
        return None
    return h, a, ko


def _finite(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def _selection(q: Mapping[str, Any]):
    market, side, line, odds = q.get("market"), q.get("side"), q.get("line"), q.get("odds")
    if not isinstance(market, str) or market not in MARKETS:
        return None
    if not isinstance(side, str) or side not in MARKETS[market]:
        return None
    if not _finite(odds) or -100 < odds < 100:
        return None
    if market == "ML":
        if line is not None:
            return None
    elif not _finite(line):
        return None
    return market, side, (float(line) if line is not None else None)


def verify_quote_pair(dk_quote: Optional[Mapping[str, Any]], independent: Optional[Mapping[str, Any]], *,
                      now: datetime, allowlist: FrozenSet[str] = INDEPENDENT_SOURCE_ALLOWLIST) -> QuoteGateResult:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_MUST_BE_TZ_AWARE")
    now = now.astimezone(timezone.utc)
    if not isinstance(dk_quote, Mapping):
        return _fail("DK_QUOTE_UNAVAILABLE")
    if not isinstance(independent, Mapping):
        return _fail("INDEPENDENT_PRICE_UNAVAILABLE")
    if dk_quote.get("source") not in DK_RENDERED_SOURCES:
        return _fail("DK_SOURCE_NOT_RENDERED_PAGE")
    labels = [_norm(independent.get(f)) for f in _LABEL_FIELDS]
    if any(_is_espn_label(n) or _is_dk_label(n) for n in labels if n):
        return _fail("INDEPENDENT_SOURCE_NOT_INDEPENDENT")
    src = independent.get("source")
    if not isinstance(src, str) or not src.strip() or src not in allowlist:
        return _fail("INDEPENDENT_PRICE_UNAVAILABLE")
    dk_id, ind_id = _identity(dk_quote), _identity(independent)
    if dk_id is None:
        return _fail("DK_GAME_IDENTITY_INVALID")
    if ind_id is None:
        return _fail("INDEPENDENT_GAME_IDENTITY_INVALID")
    if dk_id != ind_id:
        return _fail("GAME_IDENTITY_MISMATCH")
    dk_sel, ind_sel = _selection(dk_quote), _selection(independent)
    if dk_sel is None:
        return _fail("DK_SELECTION_INVALID")
    if ind_sel is None:
        return _fail("INDEPENDENT_SELECTION_INVALID")
    if dk_sel != ind_sel:
        return _fail("MARKET_SELECTION_MISMATCH")
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
