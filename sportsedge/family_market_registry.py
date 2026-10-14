"""Independent family-level research gate; not a replacement for canonical Phase-1 coverage.

Call before any CFB/NBA/CBB pricer and after existing sport-specific exclusions.
The caller must enforce the returned BLOCKED decision; no activation authority.
"""
from __future__ import annotations

FAMILIES = frozenset({"CFB", "NBA", "CBB"})
ALIASES = {"ML": "moneyline", "MONEYLINE": "moneyline", "SPREAD": "spread",
           "TOTAL": "total", "TOTALS": "total"}


def family_market_decision(sport, market):
    sport = str(sport or "").upper()
    if sport not in FAMILIES:
        return None
    family = ALIASES.get(str(market or "").strip().upper())
    return {
        "sport": sport, "market": family or str(market or ""),
        "state": "BLOCKED",
        "blocker": "NO_VALIDATION" if family else "NO_ENGINE",
        "reason": ("FAMILY_REGISTRY_NOT_VALIDATED" if family
                   else "FAMILY_MARKET_UNREGISTERED"),
        "validation_status": "UNVALIDATED",
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
