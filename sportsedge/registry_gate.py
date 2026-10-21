"""Family-level runtime registry gate for CFB/NBA/CBB (Grok t134, #2219).

Closes the #2217 bypasses found in t132: ``family_market_decision`` had no
production caller and workflow-invoked CFB/NBA runners carried no gate.

Order of checks (fail closed, exclusion first):
  1. CFB Illinois-college exclusion (central ``artifacts.free_models``
     name list). An excluded game keeps its ``ILLINOIS_COLLEGE_EXCLUDED``
     reason; the family gate never replaces it.
  2. ``sportsedge.family_market_registry.family_market_decision``. Every
     CFB/NBA/CBB market is BLOCKED (NO_VALIDATION / NO_ENGINE) until a
     family entry is validated by a separate governance ruling.
A blocked row never carries a probability, price or EV. No activation.

Owner ruling 2026-10-20 (decision packet Option B): the CFB moneyline /
spread / total families are REGISTERED_RESEARCH_ONLY / NOT_VALIDATED
(eligible False, promotable False). A priced row in one of those three
families -- and only those -- keeps its pricing keys through this gate
when the row carries satisfied Form 2 identity evidence for BOTH teams
of its fixture (see ``form2_identity_satisfied``). Unresolved, stale or
missing identity evidence leaves the row blocked exactly as before;
the Illinois exclusion still fires first; CFB player-prop and
team-total families, and all NBA/CBB families, are unchanged.

Owner directive 2026-10-20 ("Build the engines"): the NBA points /
rebounds / assists / PRA families are REGISTERED_RESEARCH_ONLY /
NOT_VALIDATED with the engine built in
``sportsedge.nba_prop_empirical``. A priced row in one of those four
families -- and only those -- keeps its pricing keys through this
gate when the row carries the registered engine's sufficiency stamp
(see ``nba_engine_sufficiency_met``): the engine priced the row from
>= 10 point-in-time prior games. NBA has no Form 2 identity concept
and none is imported here; NBA game markets and every other NBA/CBB
family are unchanged.
"""
from __future__ import annotations

from sportsedge.family_market_registry import FAMILIES, family_market_decision

FAMILY_SPORTS = FAMILIES
PRICING_KEYS = frozenset({
    "model_p", "model_prob", "model_probability", "probability", "prob",
    "ev_per_dollar", "fair_decimal", "model_conditional_p", "model_push_p",
    "push_p", "loss_p", "edge_pp", "edge_over_break_even_pp",
    "edge_vs_dk_no_vig_pp", "home_mean", "away_mean", "projected_total",
    "projected_home_margin",
    "p_model", "estimate_p", "fair_p", "fair_prob", "fair_odds", "fair_price",
    "fair_american", "ev", "edge", "expected_value", "model_price",
    "p_over", "p_under", "p_side", "win_prob", "p_home", "p_away",
    "home_win_prob", "model_spread", "model_total", "model_line",
    "pred_margin", "pred_total", "kelly", "stake", "units",
})
_TEAM_KEYS = ("home", "away", "home_team", "away_team", "team", "opponent")


def _norm(name) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " "
                            for c in str(name or "")).split())


def illinois_exclusion(sport, row) -> str | None:
    """'ILLINOIS_COLLEGE_EXCLUDED' when a CFB row names an Illinois college."""
    if str(sport or "").upper() != "CFB" or not isinstance(row, dict):
        return None
    from artifacts.free_models import IL_COLLEGE_NAMES
    for key in _TEAM_KEYS:
        value = row.get(key)
        if isinstance(value, str) and _norm(value) in IL_COLLEGE_NAMES:
            return "ILLINOIS_COLLEGE_EXCLUDED"
    return None


# The Form 2 identity-limb satisfied status, verbatim from
# sportsedge.prepricing.qb_identity_evidence.STATUS_SATISFIED (pinned by
# test: the two must never drift apart). Defined locally so this gate
# stays import-light; identity evidence is never inferred from
# availability labels -- AVAILABILITY_UNVERIFIED accompanies a Form 2
# pricing but is not identity evidence.
FORM2_IDENTITY_SATISFIED_STATUS = "QB_IDENTITY_SATISFIED_FORM2_DEPTH_ROSTER_COMPOSITE"


def _form2_verdict_satisfied(verdict) -> bool:
    return (isinstance(verdict, dict) and verdict.get("ok") is True
            and verdict.get("status") == FORM2_IDENTITY_SATISFIED_STATUS)


def form2_identity_satisfied(row) -> bool:
    """True when a row carries satisfied Form 2 identity for BOTH teams.

    Accepts the two shapes the existing Form 2 path produces:

    * the pre-pricing stage verdict map (``stage["qb_form2_identities"]``
      in sportsedge.prepricing.factor_ingestion): ``row`` carries
      ``qb_form2_identities`` with HOME and AWAY verdicts, each ``ok``
      and at the satisfied status. A present map that lacks either
      side, or carries a stale (QB_DEPTH_EVIDENCE_STALE), ambiguous or
      unresolved verdict, is NOT satisfied.
    * the per-fixture record field used by the research annex and the
      QB passing distribution records: ``identity_status`` equal to
      the satisfied status.

    Anything else -- missing evidence, a non-Form-2 status, a bare
    availability label -- is not satisfied. Fail closed.
    """
    if not isinstance(row, dict):
        return False
    verdicts = row.get("qb_form2_identities")
    if isinstance(verdicts, dict) and verdicts:
        return (_form2_verdict_satisfied(verdicts.get("HOME"))
                and _form2_verdict_satisfied(verdicts.get("AWAY")))
    return row.get("identity_status") == FORM2_IDENTITY_SATISFIED_STATUS


# The registered NBA prop engine and its sufficiency floor, mirroring
# sportsedge.nba_prop_empirical (ENGINE_ID / MIN_PRIOR_GAMES). Defined
# locally so this gate stays import-light; the engine's stamp on a
# priced row is the evidence this gate verifies — the same
# row-carried-evidence posture as the Form 2 identity shapes above.
NBA_PROP_ENGINE_ID = "NBA_PROP_EMPIRICAL_V1"
NBA_PROP_MIN_PRIOR_GAMES = 10


def nba_engine_sufficiency_met(row) -> bool:
    """True when a row carries the registered NBA prop engine's stamp
    with sufficiency met: the engine priced the row from at least
    ``NBA_PROP_MIN_PRIOR_GAMES`` point-in-time prior games. Any other
    shape — missing stamp, a different engine, a non-integer or
    below-floor prior count, sufficiency not literally True — is not
    met. Fail closed."""
    if not isinstance(row, dict):
        return False
    stamp = row.get("nba_prop_engine")
    if not isinstance(stamp, dict):
        return False
    if stamp.get("engine_id") != NBA_PROP_ENGINE_ID:
        return False
    if stamp.get("sufficiency_met") is not True:
        return False
    n = stamp.get("n_prior")
    return (isinstance(n, int) and not isinstance(n, bool)
            and n >= NBA_PROP_MIN_PRIOR_GAMES)


def research_pricing_allowed(sport, market, row) -> bool:
    """Pass conditions for REGISTERED_RESEARCH_ONLY families:

    * CFB moneyline/spread/total (Option B): fixture identity
      satisfied under the Form 2 path, on a fixture the Illinois
      exclusion does not claim.
    * NBA points/rebounds/assists/PRA ("Build the engines"): the
      registered engine's sufficiency stamp on the row.

    Everything else stays gated.
    """
    sport = str(sport or "").upper()
    if not isinstance(row, dict):
        return False
    if sport == "NBA":
        decision = family_market_decision(sport, market)
        if (decision is None
                or decision.get("state") != "REGISTERED_RESEARCH_ONLY"):
            return False
        return nba_engine_sufficiency_met(row)
    if sport != "CFB":
        return False
    if illinois_exclusion(sport, row):
        return False
    decision = family_market_decision(sport, market)
    if decision is None or decision.get("state") != "REGISTERED_RESEARCH_ONLY":
        return False
    return form2_identity_satisfied(row)


def _research_pricing_stamp(decision):
    """Registration metadata stamped on a row the gate lets price."""
    if decision.get("pricing_condition") == "ENGINE_SUFFICIENCY_MET":
        disposition = "RESEARCH_PRICING_ALLOWED_ENGINE_SUFFICIENCY_MET"
    else:
        disposition = "RESEARCH_PRICING_ALLOWED_FORM2_IDENTITY_SATISFIED"
    return {
        "family_decision": decision,
        "coverage_market": decision["market"],
        "registration_state": decision["registration_state"],
        "validation_status": decision["validation_status"],
        "eligible": False, "promotable": False,
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "registry_enforced": True,
        "registry_module": "sportsedge.registry_gate",
        "registry_disposition": disposition,
    }


def family_gate_row(sport, market, row=None):
    """Blocked card row for a CFB/NBA/CBB line, or None for other sports."""
    sport = str(sport or "").upper()
    if sport not in FAMILY_SPORTS:
        return None
    row = row if isinstance(row, dict) else {}
    decision = family_market_decision(sport, market)
    excluded = illinois_exclusion(sport, row)
    reason = excluded or decision["reason"]
    if excluded:
        suffix = ": " + decision["reason"]
    elif (decision.get("state") == "REGISTERED_RESEARCH_ONLY"
          and decision.get("pricing_condition") == "ENGINE_SUFFICIENCY_MET"):
        suffix = (": family registry state REGISTERED_RESEARCH_ONLY, "
                  "validation NOT_VALIDATED; research pricing requires "
                  "the registered engine's sufficiency gate "
                  "(>= 10 point-in-time prior games)")
    elif decision.get("state") == "REGISTERED_RESEARCH_ONLY":
        suffix = (": family registry state REGISTERED_RESEARCH_ONLY, "
                  "validation NOT_VALIDATED; research pricing requires "
                  "satisfied Form 2 identity for both teams")
    else:
        suffix = ": family registry state BLOCKED, validation UNVALIDATED"
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": reason + suffix,
        "blocker": "ILLINOIS_COLLEGE_EXCLUDED" if excluded else decision["blocker"],
        "family_decision": decision,
        "coverage_market": decision["market"],
        "sport": sport, "market": row.get("market", market),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "registry_enforced": True, "registry_module": "sportsedge.registry_gate",
    }


def _row_market(d: dict):
    for k in ("market", "market_key", "market_type", "bet_type", "coverage_market"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def is_priced(d: dict) -> bool:
    return any(d.get(k) is not None for k in PRICING_KEYS)


def gate_payload(obj, default_sport=None, *, _sport=None, stats=None):
    """Recursively strip prices from every CFB/NBA/CBB row before writing.

    Any dict in a family sport that carries a pricing key is replaced by its
    family blocker row (identity fields kept, pricing keys and nested
    structures dropped). Returns (gated, stats) at top level.
    """
    top = stats is None
    if top:
        stats = {"checked": 0, "blocked": 0, "illinois_excluded": 0}
    sport = _sport or default_sport
    if isinstance(obj, dict):
        sp = obj.get("sport") or obj.get("league")
        if isinstance(sp, str) and sp.strip():
            sport = sp.strip().upper()
        if str(sport or "").upper() in FAMILY_SPORTS and is_priced(obj):
            stats["checked"] += 1
            market = _row_market(obj) or "UNSPECIFIED"
            if research_pricing_allowed(sport, market, obj):
                # A REGISTERED_RESEARCH_ONLY row whose per-family
                # pricing condition is met (CFB: satisfied Form 2
                # identity for both teams; NBA props: the registered
                # engine's sufficiency stamp) keeps its pricing keys,
                # stamped with the research registration. Nested values
                # are still gated on their own merits.
                stats["research_priced"] = stats.get("research_priced", 0) + 1
                sport_key = f"research_priced_{str(sport).lower()}"
                stats[sport_key] = stats.get(sport_key, 0) + 1
                res = {k: gate_payload(v, None, _sport=sport, stats=stats)
                       for k, v in obj.items()}
                res.update(_research_pricing_stamp(
                    family_market_decision(sport, market)))
                return (res, stats) if top else res
            gate = family_gate_row(sport, market, obj)
            stats["illinois_excluded" if gate["blocker"] == "ILLINOIS_COLLEGE_EXCLUDED"
                  else "blocked"] += 1
            keep = {k: v for k, v in obj.items()
                    if k not in PRICING_KEYS and not isinstance(v, (dict, list))}
            keep.update(gate)
            if obj.get("market") is None:
                keep["market"] = _row_market(obj)
            return (keep, stats) if top else keep
        res = {k: gate_payload(v, None, _sport=sport, stats=stats) for k, v in obj.items()}
    elif isinstance(obj, list):
        res = [gate_payload(v, None, _sport=sport, stats=stats) for v in obj]
    else:
        res = obj
    return (res, stats) if top else res


def gate_and_stamp(payload, default_sport, runner: str):
    gated, stats = gate_payload(payload, default_sport)
    if isinstance(gated, dict):
        cfb_priced = bool(stats.get("research_priced_cfb"))
        nba_priced = bool(stats.get("research_priced_nba"))
        if cfb_priced and nba_priced:
            family_state = "BLOCKED_WITH_CFB_AND_NBA_RESEARCH_PRICING"
        elif nba_priced:
            family_state = "BLOCKED_WITH_NBA_RESEARCH_PRICING"
        elif cfb_priced or stats.get("research_priced"):
            family_state = "BLOCKED_WITH_CFB_RESEARCH_PRICING"
        else:
            family_state = "BLOCKED"
        gated["registry_gate"] = {
            "runner": runner,
            "module": "sportsedge.registry_gate",
            "family_state": family_state,
            **stats}
    return gated


def gate_text(text: str, sport, runner: str) -> str:
    """Rendered text for a family sport is replaced by a blocked notice."""
    if str(sport or "").upper() not in FAMILY_SPORTS:
        return text
    return (f"{str(sport).upper()} REGISTRY BLOCKED ({runner}): "
            "FAMILY_REGISTRY_NOT_VALIDATED. Research-only; no prices, "
            "probabilities or EV are published until a family entry is "
            "validated by governance ruling.\n")
