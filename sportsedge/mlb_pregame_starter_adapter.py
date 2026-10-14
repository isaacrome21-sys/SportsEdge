"""Offline pregame-starter gate for MLB F5, NRFI/YRFI and pitcher props.

Research only. The ONLY permitted source of starter identity for these
families is ``mlb_pit_binding.load_research_starter_binding`` (verified
starter_capture chain + raw bytes + receipt journal). This adapter never
fetches, never writes, never creates timestamps or probabilities, and never
grants pricing/betting/eligibility. Output is BLOCKED unless the loader
returns RESEARCH_BOUND, and the best possible action is WATCH.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

ADAPTER_SCHEMA = "SPORTSEDGE_MLB_PREGAME_STARTER_ADAPTER_V1"
F5_FAMILIES = frozenset({"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})
FIRST_INNING_FAMILIES = frozenset({"NRFI", "YRFI"})
PITCHER_PROP_FAMILIES = frozenset({
    "PITCHER_STRIKEOUTS", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED",
    "PITCHER_WALKS", "PITCHER_EARNED_RUNS",
})
NOT_OFFERED = frozenset({"MLB_STOLEN_BASES", "STOLEN_BASES"})
SUPPORTED = F5_FAMILIES | FIRST_INNING_FAMILIES | PITCHER_PROP_FAMILIES
_ACTION_RANK = {"NONE": 0, "BLOCKED": 0, "WATCH": 1}
_ZERO_AUTHORITY = {
    "pricing_authorized": False, "betting_authorized": False,
    "model_eligible": False, "research_only": True,
    "promotion_authority": False, "activation": False,
}


def _out(family: Any, status: str, reason: str | None, binding: Mapping[str, Any] | None,
         **extra: Any) -> dict[str, Any]:
    out = {"schema": ADAPTER_SCHEMA, "market_family": family, "status": status,
           "block_reason": reason, "max_action": "WATCH" if status == "WATCH" else "NONE",
           "starter_source": "load_research_starter_binding",
           "binding_status": (binding or {}).get("binding_status")}
    out.update(_ZERO_AUTHORITY)
    out.update(extra)
    return out


def _default_binder() -> Callable[..., Mapping[str, Any]]:
    from sportsedge.mlb_pit_binding import load_research_starter_binding
    return load_research_starter_binding


def gate_market_on_pregame_starters(
    market_family: Any,
    *,
    binding_kwargs: Mapping[str, Any],
    pitcher_id: Any = None,
    binder: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return BLOCKED or WATCH for one market row; never more than WATCH.

    ``binder`` exists only for tests; production callers must leave it None so
    the verified loader is used. Any exception or unexpected loader output
    fails closed.
    """
    if not isinstance(market_family, str) or market_family in NOT_OFFERED:
        return _out(market_family, "BLOCKED", "MARKET_NOT_OFFERED_OR_INVALID", None)
    if market_family not in SUPPORTED:
        return _out(market_family, "BLOCKED", "MARKET_FAMILY_NOT_STARTER_GATED", None)
    if not isinstance(binding_kwargs, Mapping):
        return _out(market_family, "BLOCKED", "BINDING_KWARGS_INVALID", None)
    if market_family in PITCHER_PROP_FAMILIES and (type(pitcher_id) is not int or pitcher_id <= 0):
        return _out(market_family, "BLOCKED", "PITCHER_ID_INVALID", None)
    try:
        binding = (binder or _default_binder())(**dict(binding_kwargs))
    except Exception as exc:  # fail closed, never repair
        return _out(market_family, "BLOCKED", f"BINDER_ERROR:{type(exc).__name__}", None)
    if not isinstance(binding, Mapping):
        return _out(market_family, "BLOCKED", "BINDING_OUTPUT_INVALID", None)
    status = binding.get("binding_status")
    if status != "RESEARCH_BOUND":
        reason = binding.get("block_reason") or "BINDING_NOT_RESEARCH_BOUND"
        return _out(market_family, "BLOCKED", f"NO_VERIFIED_PREGAME_STARTER:{reason}"[:200], binding)
    # A bound record that somehow carries authority is malformed: refuse.
    for key in ("pricing_authorized", "betting_authorized", "model_eligible", "promotion_authority"):
        if binding.get(key) is not False:
            return _out(market_family, "BLOCKED", f"BINDING_AUTHORITY_FLAG_UNEXPECTED:{key}", binding)
    if _ACTION_RANK.get(str(binding.get("max_action")), 99) > 1:
        return _out(market_family, "BLOCKED", "BINDING_MAX_ACTION_UNEXPECTED", binding)
    ids = {}
    for side in ("away", "home"):
        pid = binding.get(f"{side}_probable_id")
        if type(pid) is not int or pid <= 0:
            return _out(market_family, "BLOCKED", "BOUND_STARTER_ID_INVALID", binding)
        ids[side] = pid
    if ids["away"] == ids["home"]:
        return _out(market_family, "BLOCKED", "BOUND_STARTER_IDS_IDENTICAL", binding)
    extra: dict[str, Any] = {"away_starter_id": ids["away"], "home_starter_id": ids["home"],
                             "game_pk": binding.get("game_pk"),
                             "evidence_limits": binding.get("evidence_limits")}
    if market_family in PITCHER_PROP_FAMILIES:
        if pitcher_id not in ids.values():
            return _out(market_family, "BLOCKED", "PITCHER_NOT_BOUND_PREGAME_STARTER", binding, **extra)
        extra["pitcher_side"] = "away" if pitcher_id == ids["away"] else "home"
    return _out(market_family, "WATCH", None, binding, **extra)
