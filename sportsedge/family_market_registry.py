"""Independent family-level research gate; not a replacement for canonical Phase-1 coverage.

Call before any CFB/NBA/CBB pricer and after existing sport-specific exclusions.
The caller must enforce the returned BLOCKED decision; no activation authority.
"""
from __future__ import annotations

FAMILIES = frozenset({"CFB", "NBA", "CBB"})
ALIASES = {"ML": "moneyline", "MONEYLINE": "moneyline", "SPREAD": "spread",
           "TOTAL": "total", "TOTALS": "total",
           "H2H": "moneyline", "SPREADS": "spread",
           "POINT_SPREAD": "spread"}
CFB_ALIASES = {"TEAM_TOTAL": "team_total", "TEAM_TOTALS": "team_total"}
CFB_EVALUATION_SCOPE = {
    "moneyline": "HISTORICAL", "spread": "HISTORICAL",
    "total": "HISTORICAL", "team_total": "FORWARD_ONLY",
}


def family_market_decision(sport, market):
    sport = str(sport or "").upper()
    if sport not in FAMILIES:
        return None
    key = str(market or "").strip().upper()
    family = ALIASES.get(key)
    if sport == "CFB":
        family = CFB_ALIASES.get(key, family)
    return {
        "sport": sport, "market": family or str(market or ""),
        "state": "BLOCKED",
        "blocker": "NO_VALIDATION" if family else "NO_ENGINE",
        "reason": ("FAMILY_REGISTRY_NOT_VALIDATED" if family
                   else "FAMILY_MARKET_UNREGISTERED"),
        "validation_status": "UNVALIDATED",
        "evaluation_scope": (CFB_EVALUATION_SCOPE.get(family, "UNREGISTERED")
                             if sport == "CFB" else "UNSPECIFIED"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
