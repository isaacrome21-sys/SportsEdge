"""Named truthful blockers for the 1st-inning deep set (matrix M21).

The deep-set sub-families -- 1st-inning 3-way, run line, odd/even,
strikeouts thrown, batters-to-plate -- are NOT among the 89 matrix
markets in sportsedge.canonical_coverage (that table is the matrix
contract, exact by test), and they are not in the phone first-inning
lane's market set either. Intake rows for them used to die at the
generic NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback. This module
gives the names first-class form on the canonical card with each
sub-family's truthful blocker (the mlb_total_hits pattern):

* FIRST_INNING_3_WAY / FIRST_INNING_RUN_LINE /
  FIRST_INNING_ODD_EVEN -> FIRST_INNING_COUNT_DISTRIBUTION_UNBUILT.
  The canonical first-inning engine is BINARY (per-team
  score/no-score, Jeffreys m30 zero-rates): it emits no (away,
  home) count joint, so margin / parity / three-way mass has no
  honest source distribution. The Poisson count sibling was
  measured far worse than the binary engine at the binary itself
  (backtest Phase 2), so a count joint may only be adopted through
  its own preregistered chronological evaluation.
* FIRST_INNING_K -> FIRST_INNING_PITCHER_K_PBP_POOL_UNBUILT and
  FIRST_INNING_BATTERS_TO_PLATE ->
  FIRST_INNING_BATTERS_TO_PLATE_PBP_POOL_UNBUILT. StatsAPI
  play-by-play carries the underlying events, but no canonical-path
  construction consumes them into verified strictly-prior pools.

(Team HR Y/N and pitches/strikes already refuse by name inside the
phone first-inning lane: FIRST_INNING_HR_NOT_IN_VERIFIED_LINESCORE
and FIRST_INNING_PITCHES_NO_VERIFIED_PER_INNING_HISTORY in
sportsedge.mlb_first_inning_model.BLOCKED_MARKETS.)

Nothing here prices: every row terminates BLOCKED with the gate
named. No registry/deployment/validation state is touched.
"""
from __future__ import annotations

from typing import Any, Mapping

_COUNT_GATE = "FIRST_INNING_COUNT_DISTRIBUTION_UNBUILT"
_COUNT_DETAIL = (
    "the canonical first-inning engine prices only the binary "
    "score/no-score state per team (Jeffreys m30 zero-rates); this "
    "market needs the (away, home) first-inning COUNT joint "
    "(margin / parity / three-way mass), which does not exist on "
    "this path. The Poisson count sibling was measured far worse "
    "than the binary engine at the binary itself, so a count joint "
    "may only be adopted through its own preregistered "
    "chronological evaluation. Pricing stays refused until then.")

# canonical market -> (gate code, detail)
FIRST_INNING_DEEP_SET_GATES: dict[str, tuple[str, str]] = {
    "FIRST_INNING_3_WAY": (_COUNT_GATE, _COUNT_DETAIL),
    "FIRST_INNING_RUN_LINE": (_COUNT_GATE, _COUNT_DETAIL),
    "FIRST_INNING_ODD_EVEN": (_COUNT_GATE, _COUNT_DETAIL),
    "FIRST_INNING_K": (
        "FIRST_INNING_PITCHER_K_PBP_POOL_UNBUILT",
        "strikeouts thrown in the first inning (Y/N and exact "
        "counts) need a verified strictly-prior per-game "
        "first-inning pitcher strikeout pool built from "
        "play-by-play; StatsAPI play-by-play carries the events "
        "but no canonical-path construction consumes them into a "
        "PIT pool. Pricing stays refused until that pool exists "
        "and is verified."),
    "FIRST_INNING_BATTERS_TO_PLATE": (
        "FIRST_INNING_BATTERS_TO_PLATE_PBP_POOL_UNBUILT",
        "batters to the plate in the first inning need a verified "
        "strictly-prior per-game first-inning batters-faced pool "
        "built from play-by-play; StatsAPI play-by-play carries "
        "the events but no canonical-path construction consumes "
        "them into a PIT pool. Pricing stays refused until that "
        "pool exists and is verified."),
}

FIRST_INNING_DEEP_SET_ALIASES: dict[str, str] = {
    "FIRST_INNING_3WAY": "FIRST_INNING_3_WAY",
    "FIRST_INNING_MONEYLINE_3_WAY": "FIRST_INNING_3_WAY",
    "FIRST_INNING_ODD_OR_EVEN": "FIRST_INNING_ODD_EVEN",
    "FIRST_INNING_STRIKEOUTS": "FIRST_INNING_K",
    "FIRST_INNING_BATTERS_FACED": "FIRST_INNING_BATTERS_TO_PLATE",
}

FIRST_INNING_DEEP_SET_MARKETS = frozenset(
    FIRST_INNING_DEEP_SET_GATES) | frozenset(FIRST_INNING_DEEP_SET_ALIASES)


def canonical_deep_set_market(market: Any) -> str | None:
    """Canonical deep-set market for an intake spelling, else None."""
    name = str(market or "").strip().upper()
    if name in FIRST_INNING_DEEP_SET_GATES:
        return name
    return FIRST_INNING_DEEP_SET_ALIASES.get(name)


def deep_set_blocked_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Fail-closed card row naming the sub-family's gate.

    Returns None when the row's market is not a deep-set market.
    Row shape mirrors canonical_coverage.blocked_row_for.
    """
    canonical = canonical_deep_set_market(row.get("market"))
    if canonical is None:
        return None
    gate, detail = FIRST_INNING_DEEP_SET_GATES[canonical]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": ("NO_ENGINE: " + gate + " — " + detail)[:400],
        "blocker": "NO_ENGINE",
        "blocker_detail": detail,
        "coverage_market": canonical,
        "deep_set_gate": gate,
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
