"""Independent family-level research gate; not a replacement for canonical Phase-1 coverage.

Call before any CFB/NBA/CBB pricer and after existing sport-specific exclusions.
The caller must enforce the returned BLOCKED decision; no activation authority.
"""
from __future__ import annotations

FAMILIES = frozenset({"CFB", "NBA", "CBB"})
ALIASES = {"ML": "moneyline", "MONEYLINE": "moneyline", "SPREAD": "spread",
           "TOTAL": "total", "TOTALS": "total",
           "H2H": "moneyline", "SPREADS": "spread",
           "POINT_SPREAD": "spread",
           # t146: further odds-feed spellings (The Odds API, DK/ESPN feeds, CFBD lines)
           "MONEY_LINE": "moneyline", "MONEYLINES": "moneyline", "H2H_GAME": "moneyline",
           "POINT_SPREADS": "spread", "POINTSPREAD": "spread", "SPREAD_POINT": "spread",
           "OVER_UNDER": "total", "OVERUNDER": "total", "OU": "total",
           "GAME_TOTAL": "total", "POINTS_TOTAL": "total"}
CFB_ALIASES = {"TEAM_TOTAL": "team_total", "TEAM_TOTALS": "team_total",
               "TEAMTOTAL": "team_total", "TEAM_POINTS": "team_total",
               "TEAM_TOTAL_POINTS": "team_total"}
EVALUATION_SCOPES = frozenset({"HISTORICAL", "FORWARD_ONLY"})
CFB_EVALUATION_SCOPE = {
    "moneyline": "HISTORICAL", "spread": "HISTORICAL",
    "total": "HISTORICAL", "team_total": "FORWARD_ONLY",
}


def _canon_key(market) -> str:
    """Upper-case, hyphens/spaces/dots -> underscores (feed spellings vary)."""
    out = str(market or "").strip().upper()
    for ch in "- .":
        out = out.replace(ch, "_")
    while "__" in out:
        out = out.replace("__", "_")
    return out


def family_market_decision(sport, market):
    sport = str(sport or "").upper()
    if sport not in FAMILIES:
        return None
    key = _canon_key(market)
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


def cfb_evaluation_admissible(market, requested_scope) -> tuple[bool, str]:
    """Fail-closed scope check for CFB evaluation/freeze bookkeeping (t146).

    Admissible only when the market resolves to a registered CFB family AND the
    requested scope equals that family's declared scope. HISTORICAL evaluation of a
    FORWARD_ONLY family (team totals) is refused. Unknown or missing scope, unknown
    market and non-string input are refused. Never confers PLAY/pricing authority:
    admissibility is about which evidence may be *evaluated*, and every family
    decision remains state BLOCKED / UNVALIDATED.
    """
    if not isinstance(requested_scope, str) or requested_scope not in EVALUATION_SCOPES:
        return False, "EVALUATION_SCOPE_INVALID"
    decision = family_market_decision("CFB", market)
    declared = decision["evaluation_scope"]
    if declared not in EVALUATION_SCOPES:
        return False, "FAMILY_MARKET_UNREGISTERED"
    if declared != requested_scope:
        return False, f"SCOPE_MISMATCH:{decision['market']}:{declared}"
    return True, f"ADMISSIBLE:{decision['market']}:{declared}"
