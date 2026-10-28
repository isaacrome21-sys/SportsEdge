"""Landing check for NHL_TEAM_TOTAL_DIST_V1 — BUILD VERIFICATION ONLY.

Exercises the construction end to end on one fixture game: prices
both teams at lines 2.5 / 3.0 / 3.5 under BOTH settlement bases,
verifies pmf mass conservation, and demonstrates every named refusal
path. The rates are STAND-INS, disclosed on the output's face: no
parent rate artifact exists on main (the parent's fit is separate
build work), and this check fits nothing.

This is NOT the design screen. The family's only validation protocol
is the forward Stage B window in NHL_TEAM_TOTALS_DESIGN.md
(Dec 1, 2026 - Jan 31, 2027), gated on the Nov 30, 2026 Stage A
verdict; see SCREEN_REPORT.md in this directory for the
NOT_EXECUTABLE record. Nothing here is counted, frozen, or a claim
about hockey.

Run: python3 research/nhl_team_totals_build_20261028/landing_check.py
Writes: landing_check_result.json beside this script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sportsedge.nhl_team_total_v1 import (  # noqa: E402
    ParentGameRates,
    TeamTotalRefusal,
    price_team_total,
    team_total_pmf,
)

FIXTURE_RATES = ParentGameRates(
    game_id="landing-check-fixture",
    game_date=20261205,
    away_team="ANA",
    home_team="EDM",
    away_reg_mean=2.9,
    home_reg_mean=3.4,
    dispersion_cv=0.55,
    ot_home_win_prob=0.54,
    xg_vintages=("rebuilt_2026_27",),
    max_input_gamedate=20261204,
    pull_manifest_sha256="0" * 64,
    cross_vintage_treatment=None,
)


def _row(rates, side, line, basis):
    r = price_team_total(rates, side, line, basis)
    return {
        "team": r.team, "side": r.side, "line": r.line,
        "settlement_basis": r.settlement_basis,
        "prob_over": r.prob_over, "prob_under": r.prob_under,
        "prob_push": r.prob_push,
    }


def _refusal(rates, side, line, basis):
    try:
        price_team_total(rates, side, line, basis)
    except TeamTotalRefusal as refusal:
        return refusal.code
    return "NO_REFUSAL — DEFECT"


def main() -> int:
    rates = FIXTURE_RATES
    pmf_sums = {}
    for side in ("away", "home"):
        for basis in ("regulation", "incl_ot"):
            pmf_sums[f"{side}/{basis}"] = sum(
                team_total_pmf(rates, side, basis))
    rows = [
        _row(rates, side, line, basis)
        for side in ("away", "home")
        for basis in ("regulation", "incl_ot")
        for line in (2.5, 3.0, 3.5)
    ]
    from dataclasses import replace
    refusals = {
        "missing_basis": _refusal(rates, "home", 3.5, None),
        "same_day_input": _refusal(
            replace(rates, max_input_gamedate=rates.game_date),
            "home", 3.5, "regulation"),
        "cross_vintage_untreated": _refusal(
            replace(rates, xg_vintages=(
                "undisclosed_legacy", "rebuilt_2026_27")),
            "home", 3.5, "regulation"),
        "invalid_mean": _refusal(
            replace(rates, home_reg_mean=0.0), "home", 3.5, "regulation"),
    }
    result = {
        "check": "BUILD VERIFICATION ONLY — NOT A SCREEN, NOT COUNTED",
        "rates_provenance": "STAND-IN fixture rates; no parent rate "
                            "artifact exists on main; nothing fitted",
        "pmf_sums": pmf_sums,
        "priced_rows": rows,
        "refusals": refusals,
    }
    out = Path(__file__).with_name("landing_check_result.json")
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    ok = all(abs(s - 1.0) < 1e-9 for s in pmf_sums.values()) and all(
        v != "NO_REFUSAL — DEFECT" for v in refusals.values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
