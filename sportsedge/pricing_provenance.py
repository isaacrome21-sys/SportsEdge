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

# Availability guard (owner review of PR #2157, finding 4; issue
# #2158). A row priced on QB_IDENTITY_EVIDENCE Form 2 carries
# availability_status == AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT
# (the constant is defined in
# sportsedge.prepricing.qb_identity_evidence; the literal is repeated
# here because that module imports the engine this module serves --
# importing it would be circular). Identity was verified; the QB's
# AVAILABILITY is explicitly unknown, and a verified name must never
# be mistaken for verified availability: such a row is research-only
# BY STRUCTURE, whatever its EV or engine status claims. The guard is
# driven by the availability FIELD, never by a status string, so a
# forged candidate status cannot switch it off.
AVAILABILITY_UNVERIFIED = "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"
AVAILABILITY_RESEARCH_ONLY_STATUS = "RESEARCH_ONLY_AVAILABILITY_UNVERIFIED"
AVAILABILITY_PLAY_BLOCK = "QB_AVAILABILITY_UNVERIFIED_CANNOT_SURFACE_AS_PLAY"
AVAILABILITY_EV_PRESENTATION = "RESEARCH_ONLY_AVAILABILITY_UNVERIFIED"

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

# Owner ruling t207u: Lane A (free_models LANE_A_INDEPENDENT) is retired
# from actionable cards pending a rebuild and an independent backtest
# (recorded Brier deficits vs market: ML +0.0115, RL +0.0186, TOT +0.0224).
# Its output may appear only as a labeled research diagnostic: never a
# lean, candidate, PLAY, or position.  Historical results are untouched.
LANE_A_ENGINE_LANE = "LANE_A_INDEPENDENT"


def is_lane_a_label(value: Any) -> bool:
    """Case/whitespace-insensitive Lane A detection (audit LOW)."""
    return isinstance(value, str) and value.strip().upper() == LANE_A_ENGINE_LANE
LANE_A_RETIRED_STATUS = "RESEARCH_DIAGNOSTIC_LANE_A_RETIRED"
LANE_A_RETIRED_PLAY_BLOCK = "LANE_A_RETIRED_FROM_ACTIONABLE_CARDS_T207U"
LANE_A_RETIRED_EV_PRESENTATION = "DIAGNOSTIC_ONLY_LANE_A_RETIRED"


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
    if is_lane_a_label(lane):
        lane = LANE_A_ENGINE_LANE
    if lane == "LANE_A_INDEPENDENT":
        return {"lane": LANE_INDEPENDENT, "mechanism": None,
                "source": "FREE_MODELS_LANE_A_INDEPENDENT",
                "engine_lane": lane, "play_eligible": False,
                "retired": LANE_A_RETIRED_PLAY_BLOCK}
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


def availability_forces_research_only(row: Mapping[str, Any]) -> bool:
    """True when the row's QB availability is explicitly UNVERIFIED
    (Form 2 identity evidence): the row may appear only in research
    output carrying the availability label, never on a PLAY or
    candidate surface, regardless of EV or status."""
    return row.get("availability_status") == AVAILABILITY_UNVERIFIED


def is_play_eligible(row: Mapping[str, Any]) -> bool:
    """True only when the row's provenance is established INDEPENDENT
    and its availability is not explicitly unverified."""
    if availability_forces_research_only(row):
        return False
    if _is_lane_a(row):
        return False
    prov = row.get("pricing_provenance")
    if isinstance(prov, dict) and prov.get("lane"):
        return prov["lane"] == LANE_INDEPENDENT
    # Fall back to the engine's declared lane for rows stamped elsewhere.
    # Lane A was the only fallback-eligible lane and is retired (t207u).
    return False


def _is_lane_a(row: Mapping[str, Any]) -> bool:
    prov = row.get("pricing_provenance")
    if isinstance(prov, dict) and is_lane_a_label(prov.get("engine_lane")):
        return True
    return is_lane_a_label(row.get("pricing_lane"))


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
    - AVAILABILITY guard (issue #2158): any priced row whose
      ``availability_status`` is AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT
      is forced research-only (demoted to
      ``RESEARCH_ONLY_AVAILABILITY_UNVERIFIED`` when on a gated
      status), whatever its lane or EV -- a verified QB identity is
      not verified availability.
    """
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if is_lane_a_label(row.get("pricing_lane")):
            row["pricing_lane"] = LANE_A_ENGINE_LANE  # normalise spelling
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
        # Availability guard (issue #2158): applied on the FIELD, ahead
        # of every lane consideration, to any priced row. A play-surface
        # status is demoted outright; the row keeps its availability
        # label and its probability (research output), but it is
        # stamped research-only and play-blocked so no downstream
        # surface builder can promote it on EV alone.
        if availability_forces_research_only(row) and (
                status in GATED_STATUSES or _carries_probability(row)):
            row["research_only"] = True
            row["availability_research_only"] = True
            row["play_blocked_reason"] = AVAILABILITY_PLAY_BLOCK
            row["ev_presentation"] = AVAILABILITY_EV_PRESENTATION
            if status in GATED_STATUSES:
                row["status"] = AVAILABILITY_RESEARCH_ONLY_STATUS
                row["reason"] = (
                    AVAILABILITY_PLAY_BLOCK + ":" + AVAILABILITY_UNVERIFIED)
                changed += 1
            continue
        if status not in GATED_STATUSES:
            continue
        if _is_lane_a(row):
            row["pricing_lane"] = LANE_A_ENGINE_LANE  # normalised spelling
            # A play-surface status (lean/candidate/edge) is demoted; a
            # non-actionable PRICED_RESEARCH row keeps its status so
            # coverage accounting is unchanged, but is labeled too.
            if status in PLAY_SURFACE_STATUSES:
                row["status"] = LANE_A_RETIRED_STATUS
                changed += 1
            row["research_only"] = True
            row["research_diagnostic"] = "LANE_A_RETIRED_DIAGNOSTIC"
            row["play_blocked_reason"] = LANE_A_RETIRED_PLAY_BLOCK
            row["ev_presentation"] = LANE_A_RETIRED_EV_PRESENTATION
            if status in PLAY_SURFACE_STATUSES:
                row["reason"] = LANE_A_RETIRED_PLAY_BLOCK
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
