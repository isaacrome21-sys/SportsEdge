"""Named truthful blockers for the Plate Appearance markets (matrix M49).

DraftKings offers three per-batter first-plate-appearance forms
(enumerated on the Oct 13 2026 board, CATALOG_MLB.md): 1st PA Result
(multi-outcome), On Base Yes/No, and Grouped Result (3-way). They
are NOT among the 89 matrix markets in sportsedge.canonical_coverage
(that table is the matrix contract, exact by test). Intake rows for
them used to die at the generic NO_VERIFIED_MODEL_FOR_THIS_MARKET
fallback. This module gives the names first-class form on the
canonical card with the truthful blockers (the mlb_total_hits /
mlb_first_inning_deep_set pattern):

* All three forms -> PLATE_APPEARANCE_PBP_POOL_UNBUILT. A first-PA
  distribution needs a verified strictly-prior first-PA outcome
  pool -- per-batter first-PA results, and the opposing starter's
  first-PA-faced results -- built from play-by-play. StatsAPI
  play-by-play carries the underlying events, but no canonical-path
  construction consumes them into a PIT pool (the same structural
  gap the M21 first-inning K / batters-to-plate gates name).
* Also outstanding, named in every row's detail:
  PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED. The catalog evidence
  names the three market FORMS but not DK's exact selection lists
  for the multi-outcome result market, nor the Grouped Result
  3-way partition, so no settlement basis can be verified and no
  selection set can bind -- the prerequisite the M7 / F5-derived
  builds had and this family does not.

Nothing here prices: every row terminates BLOCKED with the gate
named. No registry/deployment/validation state is touched.
"""
from __future__ import annotations

from typing import Any, Mapping

_POOL_GATE = "PLATE_APPEARANCE_PBP_POOL_UNBUILT"
_POOL_DETAIL = (
    "a first-plate-appearance distribution needs a verified "
    "strictly-prior first-PA outcome pool (per-batter first-PA "
    "results plus the opposing starter's first-PA-faced results) "
    "built from play-by-play; StatsAPI play-by-play carries the "
    "events but no canonical-path construction consumes them into "
    "a PIT pool. Also outstanding: "
    "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED -- the catalog "
    "evidence names this market form but not DK's exact selection "
    "list, so no settlement basis can be verified and no selection "
    "set can bind. Pricing stays refused until both exist.")
_GROUPED_DETAIL = (
    "a first-plate-appearance distribution needs a verified "
    "strictly-prior first-PA outcome pool (per-batter first-PA "
    "results plus the opposing starter's first-PA-faced results) "
    "built from play-by-play; StatsAPI play-by-play carries the "
    "events but no canonical-path construction consumes them into "
    "a PIT pool. Also outstanding: "
    "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED -- the catalog "
    "evidence names the Grouped Result form but not DK's exact "
    "3-way partition of PA outcomes, so no settlement basis can be "
    "verified and no selection set can bind. Pricing stays "
    "refused until both exist.")
_BARE_DETAIL = (
    "this row names the Plate Appearance family without one of "
    "its three forms (1st PA Result / On Base Yes-No / Grouped "
    "Result); every form is gated by "
    "PLATE_APPEARANCE_PBP_POOL_UNBUILT -- no verified "
    "strictly-prior first-PA outcome pool built from play-by-play "
    "exists on the canonical path -- and by "
    "PLATE_APPEARANCE_SELECTION_SET_UNVERIFIED. Pricing stays "
    "refused.")

# canonical market -> (gate code, detail)
PLATE_APPEARANCE_GATES: dict[str, tuple[str, str]] = {
    "PLATE_APPEARANCE_RESULT": (_POOL_GATE, _POOL_DETAIL),
    "PLATE_APPEARANCE_ON_BASE": (_POOL_GATE, _POOL_DETAIL),
    "PLATE_APPEARANCE_GROUPED_RESULT": (_POOL_GATE, _GROUPED_DETAIL),
}

PLATE_APPEARANCE_ALIASES: dict[str, str] = {
    "FIRST_PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "FIRST_PLATE_APPEARANCE_RESULT": "PLATE_APPEARANCE_RESULT",
    "PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "PLATE_APPEARANCE_1ST_PA_RESULT": "PLATE_APPEARANCE_RESULT",
    "PA_ON_BASE": "PLATE_APPEARANCE_ON_BASE",
    "FIRST_PA_ON_BASE": "PLATE_APPEARANCE_ON_BASE",
    "PLATE_APPEARANCE_ON_BASE_YES_NO": "PLATE_APPEARANCE_ON_BASE",
    "PA_GROUPED_RESULT": "PLATE_APPEARANCE_GROUPED_RESULT",
    "FIRST_PA_GROUPED_RESULT": "PLATE_APPEARANCE_GROUPED_RESULT",
    "PLATE_APPEARANCE_GROUPED": "PLATE_APPEARANCE_GROUPED_RESULT",
}

PLATE_APPEARANCE_MARKETS = frozenset(PLATE_APPEARANCE_GATES) | frozenset(
    PLATE_APPEARANCE_ALIASES) | {"PLATE_APPEARANCE"}


def canonical_plate_appearance_market(market: Any) -> str | None:
    """Canonical PA market for an intake spelling, else None.

    The bare family name PLATE_APPEARANCE returns None here: it
    names no single form, and the form is resolved from the row in
    plate_appearance_blocked_row instead."""
    name = str(market or "").strip().upper()
    if name in PLATE_APPEARANCE_GATES:
        return name
    return PLATE_APPEARANCE_ALIASES.get(name)


def _infer_form(row: Mapping[str, Any]) -> str | None:
    """Form of a bare PLATE_APPEARANCE row, when the row itself
    determines it; else None."""
    selection = str(row.get("side") or row.get("selection") or "").strip().upper()
    if selection in {"YES", "NO"}:
        return "PLATE_APPEARANCE_ON_BASE"
    if "GROUP" in selection:
        return "PLATE_APPEARANCE_GROUPED_RESULT"
    if selection:
        return "PLATE_APPEARANCE_RESULT"
    return None


def plate_appearance_blocked_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Fail-closed card row naming the Plate Appearance gate.

    Returns None when the row's market is not a Plate Appearance
    market. Row shape mirrors canonical_coverage.blocked_row_for.
    """
    canonical = canonical_plate_appearance_market(row.get("market"))
    if canonical is None:
        if str(row.get("market") or "").strip().upper() != "PLATE_APPEARANCE":
            return None
        canonical = _infer_form(row) or "PLATE_APPEARANCE"
    if canonical == "PLATE_APPEARANCE":
        gate, detail = _POOL_GATE, _BARE_DETAIL
    else:
        gate, detail = PLATE_APPEARANCE_GATES[canonical]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": ("NO_ENGINE: " + gate + " — " + detail)[:400],
        "blocker": "NO_ENGINE",
        "blocker_detail": detail,
        "coverage_market": canonical,
        "plate_appearance_gate": gate,
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
