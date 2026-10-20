"""Independent family-level research gate; not a replacement for canonical Phase-1 coverage.

Call before any CFB/NBA/CBB pricer and after existing sport-specific exclusions.
The caller must enforce the returned decision; no activation authority.

Owner ruling 2026-10-20 (CFB registry gate decision packet, Option B):
the CFB game families with working pricing paths -- moneyline, spread,
total -- are REGISTERED_RESEARCH_ONLY / NOT_VALIDATED (eligible False,
promotable False), mirroring the NFL prop registration (#2371). Their
rows may price and publish as research-only LEANs ("unvalidated
estimate") only when the fixture's identity is satisfied under the
Form 2 identity path (enforced per-fixture in
``sportsedge.registry_gate``); PLAY remains impossible and the CFB
historical evaluation HOLD is untouched. Every other CFB family, and
every NBA/CBB family, stays BLOCKED exactly as before.
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
               "TEAM_TOTAL_POINTS": "team_total",
               # CFB player-prop families registered 2026-10-14 (wiring
               # completion). Keys are the canonicalized spellings emitted
               # by the CFB phone pricer / research market surface.
               "PLAYER_PASSING_YARDS": "player_passing_yards",
               "PLAYER_PASS_YARDS": "player_passing_yards",
               "PLAYER_PASS_YDS": "player_passing_yards",
               "PLAYER_PASSING_TDS": "player_passing_tds",
               "PLAYER_PASS_TDS": "player_passing_tds",
               "PLAYER_PASS_ATTEMPTS": "player_pass_attempts",
               "PLAYER_COMPLETIONS": "player_completions",
               "PLAYER_PASS_COMPLETIONS": "player_completions",
               # NOTE: the bare spelling PLAYER_INTERCEPTIONS is
               # deliberately NOT bound to this family. The same string
               # denotes the defensive-interceptions market in
               # config/football_market_surface.json (NO_ENGINE, no intake
               # path), while the QB market is interceptions *thrown*. A
               # market string that cannot distinguish a priced family
               # from an engineless one keeps the conservative
               # UNREGISTERED refusal; only the unambiguous QB spelling
               # is registered. Completing this binding is an owner call.
               "PLAYER_PASS_INTERCEPTIONS": "player_interceptions",
               "PLAYER_RUSHING_YARDS": "player_rushing_yards",
               "PLAYER_RUSH_YARDS": "player_rushing_yards",
               "PLAYER_RUSH_YDS": "player_rushing_yards",
               "PLAYER_RUSH_ATTEMPTS": "player_rush_attempts",
               "PLAYER_RECEIVING_YARDS": "player_receiving_yards",
               "PLAYER_REC_YARDS": "player_receiving_yards",
               "PLAYER_RECEPTION_YDS": "player_receiving_yards",
               "PLAYER_RECEPTIONS": "player_receptions",
               "PLAYER_RUSH_PLUS_REC_YARDS": "player_rush_plus_rec_yards",
               "PLAYER_RUSH_RECEPTION_YDS": "player_rush_plus_rec_yards",
               "PLAYER_PASS_PLUS_RUSH_YARDS": "player_pass_plus_rush_yards",
               "PLAYER_PASS_RUSH_YDS": "player_pass_plus_rush_yards"}
# The registered CFB player-prop families: exactly the families with an
# existing research pricing path (the CFB phone empirical pricer; passing
# yards additionally carries the Form 2 research distribution layer).
# CFB player markets with no engine path at all -- anytime/first TD,
# longest-play, rushing/receiving TDs, kicking, defensive stats -- remain
# deliberately UNREGISTERED, so their refusal stays NO_ENGINE, which is
# the truthful reason for them.
CFB_PLAYER_FAMILIES = frozenset({
    "player_passing_yards", "player_passing_tds", "player_pass_attempts",
    "player_completions", "player_interceptions", "player_rushing_yards",
    "player_rush_attempts", "player_receiving_yards", "player_receptions",
    "player_rush_plus_rec_yards", "player_pass_plus_rush_yards",
})
REGISTRATION_STATE_RESEARCH_ONLY = "REGISTERED_RESEARCH_ONLY"
REGISTRATION_VALIDATION_STATUS = "NOT_VALIDATED"
# CFB families registered research-only by the 2026-10-20 Option B
# ruling: exactly the game families with an existing pricing path (the
# phone game engine prices all three; the CFB run machine prices all
# three). Team totals and player props are deliberately NOT registered
# here -- they stay BLOCKED.
CFB_RESEARCH_REGISTERED_FAMILIES = frozenset({"moneyline", "spread", "total"})
EVALUATION_SCOPES = frozenset({"HISTORICAL", "FORWARD_ONLY"})
CFB_EVALUATION_SCOPE = {
    "moneyline": "HISTORICAL", "spread": "HISTORICAL",
    "total": "HISTORICAL", "team_total": "FORWARD_ONLY",
    # Player families mirror team_total: FORWARD_ONLY. No historical
    # player-prop market evidence exists in the frozen evaluation dataset
    # (pooled matched team-total count is 0; player props are absent
    # entirely) and the family's market leg is forward-only by design, so
    # cfb_evaluation_admissible keeps refusing HISTORICAL requests for
    # them. Registration changes only the refusal reason (NOT_VALIDATED
    # instead of UNREGISTERED); every family stays BLOCKED / UNVALIDATED
    # and registration confers no pricing, evaluation or PLAY authority.
    "player_passing_yards": "FORWARD_ONLY",
    "player_passing_tds": "FORWARD_ONLY",
    "player_pass_attempts": "FORWARD_ONLY",
    "player_completions": "FORWARD_ONLY",
    "player_interceptions": "FORWARD_ONLY",
    "player_rushing_yards": "FORWARD_ONLY",
    "player_rush_attempts": "FORWARD_ONLY",
    "player_receiving_yards": "FORWARD_ONLY",
    "player_receptions": "FORWARD_ONLY",
    "player_rush_plus_rec_yards": "FORWARD_ONLY",
    "player_pass_plus_rush_yards": "FORWARD_ONLY",
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
    if sport == "CFB" and family in CFB_RESEARCH_REGISTERED_FAMILIES:
        # Option B registration (2026-10-20): research pricing only,
        # gated per-fixture on satisfied Form 2 identity by the runtime
        # gate. The blocker/reason fields keep naming the refusal that
        # applies whenever that per-fixture condition is not met, so
        # existing fail-closed consumers see no change for unproven
        # fixtures. Registration is not validation and not evaluation:
        # evaluation_scope is unchanged and the evaluation HOLD stands.
        return {
            "sport": sport, "market": family,
            "state": REGISTRATION_STATE_RESEARCH_ONLY,
            "registration_state": REGISTRATION_STATE_RESEARCH_ONLY,
            "blocker": "NO_VALIDATION",
            "reason": "FAMILY_REGISTRY_NOT_VALIDATED",
            "validation_status": REGISTRATION_VALIDATION_STATUS,
            "evaluation_scope": CFB_EVALUATION_SCOPE.get(family, "UNREGISTERED"),
            "research_only": True, "official_authority": False,
            "model_p_authority": False, "staking_authority": False,
            "eligible": False, "promotable": False,
            "pricing_condition": "FORM2_IDENTITY_SATISFIED_BOTH_TEAMS",
        }
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
    admissibility is about which evidence may be *evaluated*. (The CFB game
    families' 2026-10-20 research registration changes their pricing state,
    not their evaluation scope or this admissibility check.)
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
