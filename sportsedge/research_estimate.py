"""RESEARCH_ONLY estimate annex for rows that keep a named blocker.

A research estimate is the real, unvalidated output of an existing engine,
attached to a row whose terminal status and blocker are UNCHANGED. It is a
display/research artifact only:

- it never changes a row's status, blocker or reason;
- it carries no EV, no no-vig figure and no stake;
- it is never eligible, never PLAY and never counts as validation.

``valid_research_estimate`` is the single gate presentation uses; anything
malformed, out of range or claiming eligibility/validation is rejected, so
the row simply stays a named blocker.
"""
from __future__ import annotations

from math import isfinite

RESEARCH_LABEL = "RESEARCH_ONLY_UNVALIDATED"
SCHEMA = "SPORTSEDGE_RESEARCH_ESTIMATE_V1"
NEVER_ESTIMATE_BLOCKERS = frozenset({
    "ILLINOIS_COLLEGE_EXCLUDED", "BLOCKED_IL_COLLEGE", "NO_ENGINE",
})


def _prob(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) and 0 < value < 1 else None


def fair_american(p):
    p = _prob(p)
    if p is None:
        return None
    return round(-100 * p / (1 - p)) if p >= .5 else round(100 * (1 - p) / p)


def build_research_estimate(probability, *, engine, blocker, push_p=None,
                            fair=None, quote_basis=None):
    """Return the annex dict, or None when the probability is unusable."""
    p = _prob(probability)
    if p is None or not engine or not blocker:
        return None
    if str(blocker).split(":", 1)[0].strip() in NEVER_ESTIMATE_BLOCKERS:
        return None
    push = 0.0 if push_p in (None, 0) else _prob(push_p)
    if push is None or p + push > 1 + 1e-9:
        return None
    conditional = p / (1 - push) if push else p
    est = {
        "schema": SCHEMA, "label": RESEARCH_LABEL,
        "probability": round(p, 6), "push_p": round(push, 6),
        "fair_american": fair if isinstance(fair, (int, float)) and not isinstance(fair, bool)
        else fair_american(conditional),
        "engine": str(engine), "blocker_kept": str(blocker)[:200],
        "eligible": False, "play": False, "counts_as_validation": False,
        "ev_reported": False, "staking_authority": False,
        "model_p_authority": False, "official_authority": False,
    }
    if quote_basis:
        est["quote_basis"] = str(quote_basis)[:120]
    return est


def valid_research_estimate(row):
    """The estimate dict when it is well-formed and claims no authority."""
    est = row.get("research_estimate") if isinstance(row, dict) else None
    if not isinstance(est, dict) or est.get("schema") != SCHEMA:
        return None
    if est.get("label") != RESEARCH_LABEL:
        return None
    for flag in ("eligible", "play", "counts_as_validation", "ev_reported",
                 "staking_authority", "model_p_authority", "official_authority"):
        if est.get(flag) is not False:
            return None
    if _prob(est.get("probability")) is None:
        return None
    blocker = str(est.get("blocker_kept") or "")
    if not blocker or blocker.split(":", 1)[0].strip() in NEVER_ESTIMATE_BLOCKERS:
        return None
    for key in ("blocker", "reason", "status"):
        if str(row.get(key) or "").split(":", 1)[0].strip() in NEVER_ESTIMATE_BLOCKERS:
            return None
    return est
