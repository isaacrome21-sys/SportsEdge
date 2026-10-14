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
"""
from __future__ import annotations

from sportsedge.family_market_registry import FAMILIES, family_market_decision

FAMILY_SPORTS = FAMILIES
PRICING_KEYS = frozenset({
    "model_p", "model_prob", "model_probability", "probability", "prob",
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


def family_gate_row(sport, market, row=None):
    """Blocked card row for a CFB/NBA/CBB line, or None for other sports."""
    sport = str(sport or "").upper()
    if sport not in FAMILY_SPORTS:
        return None
    row = row if isinstance(row, dict) else {}
    decision = family_market_decision(sport, market)
    excluded = illinois_exclusion(sport, row)
    reason = excluded or decision["reason"]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": reason + (": " + decision["reason"] if excluded else
                            ": family registry state BLOCKED, validation "
                            "UNVALIDATED"),
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
            gate = family_gate_row(sport, _row_market(obj) or "UNSPECIFIED", obj)
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
        gated["registry_gate"] = {"runner": runner,
                                  "module": "sportsedge.registry_gate",
                                  "family_state": "BLOCKED", **stats}
    return gated


def gate_text(text: str, sport, runner: str) -> str:
    """Rendered text for a family sport is replaced by a blocked notice."""
    if str(sport or "").upper() not in FAMILY_SPORTS:
        return text
    return (f"{str(sport).upper()} REGISTRY BLOCKED ({runner}): "
            "FAMILY_REGISTRY_NOT_VALIDATED. Research-only; no prices, "
            "probabilities or EV are published until a family entry is "
            "validated by governance ruling.\n")
