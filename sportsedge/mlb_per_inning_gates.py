"""Named truthful blockers for the per-inning 2nd-9th sets (matrix M22).

DraftKings offers, for each inning 2-9: Runs O/U (0.5/1.5), a Run
Line, and a (3 Way) inning winner; plus Result After Nth Inning
(3 Way, cumulative) for innings 2-8 (CATALOG_MLB.md, INNINGS tab).
None of these names is among the 89 matrix markets in
sportsedge.canonical_coverage (that table is the matrix contract,
exact by test). Intake rows for them used to die at the generic
NO_VERIFIED_MODEL_FOR_THIS_MARKET fallback. This module gives the
names first-class form on the canonical card with the truthful
blockers (the mlb_total_hits pattern):

* Per-inning forms (INNING_<n>_RUNS / _RUN_LINE / _3_WAY, n=2..9)
  -> PER_INNING_DISTRIBUTION_UNBUILT. A single-inning market needs
  the (away, home) run-count joint FOR THAT INNING. The canonical
  period constructions are CUMULATIVE (first 3 / 5 / 7 innings and
  the full game); no per-inning distribution exists on this path,
  and a cumulative joint cannot be differenced into honest
  per-inning mass (innings are not independent: lineup turnover,
  pitcher/bullpen state and game script couple them).
* RESULT_AFTER_INNING_<n> (n=2..8) -> RESULT_AFTER_INNING_READOUT_
  UNBUILT. The 3-way result-after form (home leads / tied / away
  leads through N) has no bound readout on the canonical path for
  any N: cumulative joints exist only for N in {3, 5, 7}, as
  deployment-gated period constructions whose declared markets do
  not include this form, and no cumulative joint exists at all for
  N in {2, 4, 6, 8}.

Nothing here prices: every row terminates BLOCKED with the gate
named. No registry/deployment/validation state is touched.
"""
from __future__ import annotations

from typing import Any, Mapping

_PER_INNING_GATE = "PER_INNING_DISTRIBUTION_UNBUILT"
_PER_INNING_DETAIL = (
    "a single-inning market needs the (away, home) run-count "
    "joint for that inning; the canonical period constructions "
    "are cumulative (first 3/5/7 innings, full game) and no "
    "per-inning distribution exists on this path -- a cumulative "
    "joint cannot be differenced into honest per-inning mass "
    "(lineup turnover, pitcher/bullpen state and game script "
    "couple the innings). Pricing stays refused until a verified "
    "per-inning construction exists.")
_RESULT_AFTER_GATE = "RESULT_AFTER_INNING_READOUT_UNBUILT"
_RESULT_AFTER_DETAIL = (
    "the 3-way result-after-inning form (home leads / tied / "
    "away leads through the inning) has no bound readout on the "
    "canonical path for any N: cumulative joints exist only for "
    "N in {3, 5, 7}, as deployment-gated period constructions "
    "whose declared markets do not include this form, and no "
    "cumulative joint exists at all for N in {2, 4, 6, 8}. "
    "Pricing stays refused.")

_ORDINALS = {2: "2ND", 3: "3RD", 4: "4TH", 5: "5TH", 6: "6TH",
             7: "7TH", 8: "8TH", 9: "9TH"}


def _build_tables() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    gates: dict[str, tuple[str, str]] = {}
    aliases: dict[str, str] = {}
    for n in range(2, 10):
        for form in ("RUNS", "RUN_LINE", "3_WAY"):
            canonical = f"INNING_{n}_{form}"
            gates[canonical] = (_PER_INNING_GATE, _PER_INNING_DETAIL)
            aliases[f"{_ORDINALS[n]}_INNING_{form}"] = canonical
        aliases[f"INNING_{n}_TOTAL_RUNS"] = f"INNING_{n}_RUNS"
        aliases[f"INNING_{n}_MONEYLINE_3_WAY"] = f"INNING_{n}_3_WAY"
        aliases[f"INNING_{n}_WINNER"] = f"INNING_{n}_3_WAY"
    for n in range(2, 9):
        canonical = f"RESULT_AFTER_INNING_{n}"
        gates[canonical] = (_RESULT_AFTER_GATE, _RESULT_AFTER_DETAIL)
        aliases[f"RESULT_AFTER_{n}_INNING"] = canonical
        aliases[f"RESULT_AFTER_{_ORDINALS[n]}_INNING"] = canonical
    return gates, aliases


# canonical market -> (gate code, detail)
PER_INNING_GATES, PER_INNING_ALIASES = _build_tables()

PER_INNING_MARKETS = frozenset(PER_INNING_GATES) | frozenset(PER_INNING_ALIASES)


def canonical_per_inning_market(market: Any) -> str | None:
    """Canonical per-inning market for an intake spelling, else None."""
    name = str(market or "").strip().upper()
    if name in PER_INNING_GATES:
        return name
    return PER_INNING_ALIASES.get(name)


def per_inning_blocked_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Fail-closed card row naming the per-inning gate.

    Returns None when the row's market is not a per-inning 2nd-9th
    market. Row shape mirrors canonical_coverage.blocked_row_for.
    """
    canonical = canonical_per_inning_market(row.get("market"))
    if canonical is None:
        return None
    gate, detail = PER_INNING_GATES[canonical]
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": ("NO_ENGINE: " + gate + " — " + detail)[:400],
        "blocker": "NO_ENGINE",
        "blocker_detail": detail,
        "coverage_market": canonical,
        "per_inning_gate": gate,
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "player_name": row.get("player_name") or row.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
