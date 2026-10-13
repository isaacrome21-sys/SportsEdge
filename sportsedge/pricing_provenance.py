"""Pricing-provenance contract (Isaac's architecture-conflict ruling,
Oct 12 2026).

Under the end-state contract, a research PLAY requires an INDEPENDENT model
probability that does not borrow the sportsbook price. Market-anchored or
residual-derived estimates may remain as separately labeled research, but
they must NOT be presented as independent projections and CANNOT qualify as
independent-model PLAYs.

This module is the single place that classifies a priced row's provenance
and enforces the PLAY gate on the canonical card path:

- ``INDEPENDENT`` -- the probability was produced without any market price
  input. (The posted *line* may still define the market threshold, as it
  does for every over/under; what is forbidden is the price/probability
  itself entering the estimate.)
- ``MARKET_ANCHORED`` -- the probability itself consumed the posted
  line/price: a shrink toward the posted line, a blend with the no-vig
  price, or a residual-from-market construction. The anchoring mechanism
  is named on the row.
- ``UNDETERMINED`` -- a priced row whose provenance cannot be established
  from the row itself. Undetermined rows fail closed
  (``PROVENANCE_UNDETERMINED``); they never default to independent.

Gate semantics: anchored rows may surface at most as WATCH, with the lane
and mechanism visible on the row; their EV is labeled anchored research and
is suppressed from every card-level +EV / edges presentation. Independent
rows are untouched.
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence

LANE_INDEPENDENT = "INDEPENDENT"
LANE_MARKET_ANCHORED = "MARKET_ANCHORED"
LANE_UNDETERMINED = "UNDETERMINED"

# Anchoring mechanisms, named on the row so the card output alone
# identifies how the market price entered the estimate.
MECHANISM_MARKET_SHRINK_15PCT = "MARKET_SHRINK_15PCT"
MECHANISM_NO_VIG_BLEND_15PCT = "NO_VIG_BLEND_15PCT"
MECHANISM_RESIDUAL_FROM_MARKET = "RESIDUAL_FROM_MARKET"

ANCHORED_WATCH_STATUS = "WATCH_MARKET_ANCHORED_RESEARCH"
UNDETERMINED_STATUS = "BLOCKED_PROVENANCE_UNDETERMINED"
UNDETERMINED_REASON = "PROVENANCE_UNDETERMINED"
ANCHORED_PLAY_BLOCK = "MARKET_ANCHORED_CANNOT_QUALIFY_AS_INDEPENDENT_PLAY"
ANCHORED_EV_PRESENTATION = "ANCHORED_RESEARCH_ONLY_NOT_A_PLAY"

# Statuses that place a row on a card PLAY surface (the engine's positive-EV
# list and the bridge's research-candidate list), plus PRICED_RESEARCH --
# a priced row that is not itself a play but must still carry provenance
# and must still be capped at WATCH when anchored.
PLAY_SURFACE_STATUSES = frozenset({
    "RESEARCH_POSITIVE_EV_UNVALIDATED",
    "RESEARCH_CANDIDATE_NOT_VALIDATED",
    # Phase 7 quarter/margin/alternate coverage emits RESEARCH_EDGE on
    # theoretical EV. It must NOT bypass provenance simply because its
    # status spelling differs from the canonical game/prop lanes.
    "RESEARCH_EDGE",
})
GATED_STATUSES = PLAY_SURFACE_STATUSES | {"PRICED_RESEARCH"}


def game_lane_mechanism(market: Any) -> str:
    """How free_models Lane B anchors each market family.

    ML blends the win probability toward the market no-vig probability;
    TOTAL/SPREAD shrink the score means toward the posted line.
    """
    if str(market or "").upper() == "ML":
        return MECHANISM_NO_VIG_BLEND_15PCT
    return MECHANISM_MARKET_SHRINK_15PCT


def provenance_for_game_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a free_models game result from its declared pricing lane."""
    lane = str(result.get("pricing_lane") or "")
    if lane == "LANE_A_INDEPENDENT":
        return {"lane": LANE_INDEPENDENT, "mechanism": None,
                "source": "FREE_MODELS_LANE_A_INDEPENDENT",
                "engine_lane": lane, "play_eligible": True}
    if lane == "LANE_B_ANCHORED":
        return {"lane": LANE_MARKET_ANCHORED,
                "mechanism": game_lane_mechanism(result.get("market")),
                "source": "FREE_MODELS_LANE_B_ANCHORED",
                "engine_lane": lane, "play_eligible": False}
    return {"lane": LANE_UNDETERMINED, "mechanism": None,
            "source": "PRICING_LANE_MISSING_OR_UNRECOGNIZED",
            "engine_lane": lane or None, "play_eligible": False}


def provenance_for_bridge_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Classify a research-bridge row.

    The bridge (sportsedge.research_three_sport_bridge) only emits a
    probability for model rows that declared ``market_blind is True`` with a
    named ``model_source``; the DK odds are used solely for the EV
    comparison after the fact. A row carrying the bridge's probability
    fields is therefore independent by the bridge's own contract.
    """
    if row.get("model_probability") is not None and row.get("model_source"):
        return {"lane": LANE_INDEPENDENT, "mechanism": None,
                "source": "RESEARCH_BRIDGE_MARKET_BLIND:"
                          + str(row["model_source"]),
                "engine_lane": None, "play_eligible": True}
    return None


def _carries_probability(row: Mapping[str, Any]) -> bool:
    return (row.get("estimate_p") is not None
            or row.get("model_probability") is not None
            or isinstance(row.get("model_probabilities"), dict))


def determine_provenance(
    row: Mapping[str, Any],
    *,
    distribution_provenance: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Best-effort provenance for an evaluated row on the canonical path.

    Returns a provenance dict for every priced row, or ``None`` when the
    row carries no probability (blocked rows need no lane). A priced row
    whose provenance cannot be established returns UNDETERMINED -- it never
    defaults to independent.

    ``distribution_provenance`` maps a derivative fixture key
    ``(AWAY, HOME)`` to the provenance of the joint score distribution that
    priced the row (inherited from its source), for the derivative stage.
    """
    existing = row.get("pricing_provenance")
    if isinstance(existing, dict) and existing.get("lane"):
        return dict(existing)
    if row.get("pricing_lane"):
        return provenance_for_game_result(row)
    bridge = provenance_for_bridge_row(row)
    if bridge is not None:
        return bridge
    if (row.get("status") == "PRICED_RESEARCH"
            and isinstance(row.get("model_probabilities"), dict)):
        key = (str(row.get("away_team") or "").strip().upper(),
               str(row.get("home_team") or "").strip().upper())
        inherited = (distribution_provenance or {}).get(key)
        if isinstance(inherited, dict) and inherited.get("lane"):
            out = dict(inherited)
            out["via"] = "JOINT_SCORE_DISTRIBUTION"
            return out
        return {"lane": LANE_UNDETERMINED, "mechanism": None,
                "source": "DERIVATIVE_DISTRIBUTION_PROVENANCE_MISSING",
                "engine_lane": None, "play_eligible": False}
    if _carries_probability(row):
        return {"lane": LANE_UNDETERMINED, "mechanism": None,
                "source": "NO_PROVENANCE_MARKERS_ON_PRICED_ROW",
                "engine_lane": None, "play_eligible": False}
    return None


def is_play_eligible(row: Mapping[str, Any]) -> bool:
    """True only when the row's provenance is established INDEPENDENT."""
    prov = row.get("pricing_provenance")
    if isinstance(prov, dict) and prov.get("lane"):
        return prov["lane"] == LANE_INDEPENDENT
    # Fall back to the engine's declared lane for rows stamped elsewhere.
    return row.get("pricing_lane") == "LANE_A_INDEPENDENT"


def apply_play_gate(
    rows: Sequence[MutableMapping[str, Any]],
    *,
    distribution_provenance: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> int:
    """Stamp provenance on every priced row and enforce the PLAY gate.

    Mutates rows in place; returns the number of rows demoted or blocked.

    - MARKET_ANCHORED rows on a gated status are demoted to
      ``WATCH_MARKET_ANCHORED_RESEARCH`` with the mechanism named; their EV
      stays on the row only as labeled anchored research.
    - Priced rows on a gated status whose provenance is UNDETERMINED fail
      closed as ``BLOCKED_PROVENANCE_UNDETERMINED`` /
      ``PROVENANCE_UNDETERMINED``.
    - INDEPENDENT rows, and rows without a probability, are untouched
      apart from the provenance stamp itself.
    """
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        prov = determine_provenance(
            row, distribution_provenance=distribution_provenance)
        status = row.get("status")
        if prov is None:
            if status not in GATED_STATUSES:
                continue
            # A row on a play surface with no provenance markers at all is
            # exactly the unlabeled case the ruling closes: fail closed.
            prov = {"lane": LANE_UNDETERMINED, "mechanism": None,
                    "source": "NO_PROVENANCE_MARKERS_ON_PLAY_SURFACE_ROW",
                    "engine_lane": None, "play_eligible": False}
        row["pricing_provenance"] = prov
        if status not in GATED_STATUSES:
            continue
        if prov["lane"] == LANE_MARKET_ANCHORED:
            row["status"] = ANCHORED_WATCH_STATUS
            row["play_blocked_reason"] = ANCHORED_PLAY_BLOCK
            row["ev_presentation"] = ANCHORED_EV_PRESENTATION
            row["reason"] = (
                ANCHORED_PLAY_BLOCK + ":"
                + str(prov.get("mechanism") or "MECHANISM_UNSPECIFIED"))
            changed += 1
        elif prov["lane"] == LANE_UNDETERMINED:
            row["status"] = UNDETERMINED_STATUS
            row["play_blocked_reason"] = UNDETERMINED_REASON
            row["reason"] = (
                UNDETERMINED_REASON + ":"
                + str(prov.get("source") or "UNKNOWN"))
            changed += 1
    return changed
