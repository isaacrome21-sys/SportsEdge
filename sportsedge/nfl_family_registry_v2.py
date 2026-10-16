"""Versioned NFL family registry v2 (research registration only).

Registers the NFL player-prop families named by issue #2265 in the
canonical coverage authority, without mutating the frozen governance
surface (``config/football_prop_engine_surface.json``) or the Phase 1
coverage matrix.  The surface continues to declare NO_ENGINE for NFL
player props: every family registered here remains BLOCKED on the
canonical path, with a named registration state (NOT_VALIDATED,
eligible=false, research-only, non-promotable) and a settlement
contract.  Registration grants no pricing, admission, promotion, or
betting authority; a family leaves this state only through the separate
engine-validation and governance-admission process.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

_PATH = Path(__file__).resolve().parents[1] / "config" / "nfl_family_registry_v2.json"
GOVERNANCE_SURFACE_SHA256 = "5195611559b0634bf92bd02d2f298d36274f2ffc8c9833de7ecbe4b881303a61"
REGISTRATION_STATE = "REGISTERED_RESEARCH_ONLY"
VALIDATION_STATUS = "NOT_VALIDATED"


def load_registry_v2() -> dict[str, Any]:
    reg = json.loads(_PATH.read_text())
    if reg["extends"]["catalog_sha256"] != GOVERNANCE_SURFACE_SHA256:
        raise ValueError("NFL_REGISTRY_V2_SURFACE_PIN_MISMATCH")
    for name, fam in reg["families"].items():
        if fam.get("promotable") is not False:
            raise ValueError(f"NFL_REGISTRY_V2_PROMOTABLE_FORBIDDEN:{name}")
        if fam.get("eligible") is not False:
            raise ValueError(f"NFL_REGISTRY_V2_ELIGIBLE_FORBIDDEN:{name}")
        if fam.get("status") != "RESEARCH_ONLY":
            raise ValueError(f"NFL_REGISTRY_V2_STATUS_FORBIDDEN:{name}")
        if fam.get("registration_state") != REGISTRATION_STATE:
            raise ValueError(f"NFL_REGISTRY_V2_STATE_FORBIDDEN:{name}")
        if fam.get("validation_status") != VALIDATION_STATUS:
            raise ValueError(f"NFL_REGISTRY_V2_VALIDATION_FORBIDDEN:{name}")
    return reg


REGISTRY_V2 = load_registry_v2()


def registered_family(market: str) -> dict[str, Any] | None:
    return REGISTRY_V2["families"].get(str(market or ""))


def coverage_registration_v2(sport: str, market: str) -> dict[str, Any] | None:
    """Registration metadata for a canonical NFL prop resolution.

    Returns the governed registration fields for a family registered in
    this registry, or None.  This is metadata layered onto the existing
    BLOCKED resolution in ``sportsedge.canonical_coverage``; it never
    changes a family's state, blocker, or pricing disposition.
    """
    if str(sport).upper() != "NFL":
        return None
    fam = registered_family(market)
    if fam is None:
        return None
    return {
        "registry_schema": REGISTRY_V2["schema_version"],
        "registration_state": fam["registration_state"],
        "evidence_group": fam["evidence_group"],
        "research_only": True,
        "promotable": False,
        "eligible": False,
        "validation_status": fam["validation_status"],
    }


def settle_nfl_prop_stat(market: str, stat: Mapping[str, Any], line: float,
                         side: str) -> str:
    """Settle one registered NFL prop family from its official final stat.

    Fail-closed, mirroring the v2 MLB settlement contract: the family's
    settlement stat must be present as a non-negative integer count, the
    line must be a finite non-negative real, and the side must be OVER
    or UNDER.  YES-only families settle as OVER 0.5 on the same count
    (a YES price is an OVER 0.5 quote; no separate settlement exists).
    """
    fam = registered_family(market)
    if fam is None:
        raise ValueError(f"NFL_PROP_UNREGISTERED_FAMILY:{market}")
    field = fam["settlement_field"]
    n = stat.get(field) if isinstance(stat, Mapping) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError(f"NFL_PROP_OFFICIAL_STAT_MISSING:{field}")
    try:
        valid_line = (not isinstance(line, bool)
                      and isinstance(line, (int, float))
                      and math.isfinite(line) and line >= 0)
    except (OverflowError, TypeError, ValueError):
        valid_line = False
    if not valid_line:
        raise ValueError("NFL_PROP_LINE_INVALID")
    s = str(side).strip().upper()
    if s not in {"OVER", "UNDER"}:
        raise ValueError(f"NFL_PROP_SIDE_INVALID:{side}")
    if n == line:
        return "PUSH"
    over = n > line
    return "WIN" if over == (s == "OVER") else "LOSS"
