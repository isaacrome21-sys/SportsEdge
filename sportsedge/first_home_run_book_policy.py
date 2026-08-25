"""Normalized sportsbook settlement semantics for FIRST_HOME_RUN no-HR games.

This module does not encode any sportsbook's rule. It only validates a captured,
book-specific rule artifact and exposes the normalized result for each binary side.
"""
from __future__ import annotations

from typing import Any, Mapping

FIRST_HOME_RUN_NO_HR_RULE = "FIRST_HOME_RUN_BOOK_SPECIFIC_NO_HR_VOID_RULES"
_ALLOWED_NO_HR_RESULT_PAIRS = frozenset({("LOSS", "WIN"), ("VOID", "VOID")})


def normalized_no_hr_policy_from_record(record: Any) -> dict[str, str] | None:
    """Return a validated side-complete no-HR policy, otherwise ``None``.

    Accepted normalized semantics are deliberately narrow:
    - event-false: YES loses and NO wins;
    - void-all: both YES and NO are void.

    Any metadata-only, one-sided, mixed-void, or contradictory artifact fails closed.
    """
    if not isinstance(record, Mapping):
        return None
    normalized = record.get("normalized_policy")
    if not isinstance(normalized, Mapping):
        return None
    no_home_run = normalized.get("no_home_run")
    if not isinstance(no_home_run, Mapping):
        return None
    yes = str(no_home_run.get("YES") or "").strip().upper()
    no = str(no_home_run.get("NO") or "").strip().upper()
    if (yes, no) not in _ALLOWED_NO_HR_RESULT_PAIRS:
        return None
    return {"YES": yes, "NO": no}


def normalized_no_hr_policy(rule_evidence: Any) -> dict[str, str] | None:
    if not isinstance(rule_evidence, Mapping):
        return None
    return normalized_no_hr_policy_from_record(rule_evidence.get(FIRST_HOME_RUN_NO_HR_RULE))


def no_hr_result(policy: Any, side: Any) -> str | None:
    if not isinstance(policy, Mapping):
        return None
    direction = str(side or "").strip().upper()
    if direction not in {"YES", "NO"}:
        return None
    value = str(policy.get(direction) or "").strip().upper()
    if value not in {"WIN", "LOSS", "VOID"}:
        return None
    return value
