"""Research harness entrypoint for the NFL joint-score factory.

NOT part of the production card path.  Builds PIT-clean frozen profiles,
simulates a joint score distribution with the integrated Engine A+C
simulator, and prices team-total / period / alternate derivative rows
through the canonical derivative stage
(``sportsedge.nfl_phone_derivative_pricing``) -- the seam that fails
closed on the production path today for lack of a distribution.

Every output carries research-only / NOT_VALIDATED labels.  The lines
below are pricer predicates only (the markets being priced); they are
never inputs to the profiles or the simulation.

Worked example (defaults): SEA @ DEN, 2026 Week 7 -- the Oct 15, 2026
Thursday-night fixture, priced at the DraftKings team totals posted that
night (DEN 19.5 / SEA 20.5), the 40.5 game total, a -2.5 spread, and a
selection of period/alternate predicates.  The frozen profile fit
(2022-2025 REG) is strictly prior to the 2026 season, so the fixture is
PIT-eligible.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.nfl_joint_score_research import (  # noqa: E402
    RESEARCH_LABELS,
    build_game_profiles,
    load_frozen_profile_source,
    price_research_derivatives,
    simulate_joint_score_rows,
)
from sportsedge.sports.nfl.team_totals import price_nfl_team_totals  # noqa: E402


def worked_example_intake(home: str, away: str) -> list[dict]:
    base = {"away": away, "home": home, "sport": "NFL"}
    return [
        {**base, "market": "TEAM_TOTALS", "side": "HOME", "team": home, "line": 19.5},
        {**base, "market": "TEAM_TOTALS", "side": "AWAY", "team": away, "line": 20.5},
        {**base, "market": "FIRST_HALF_TOTAL", "line": 20.5},
        {**base, "market": "FIRST_HALF_SPREAD", "line": -1.5},
        {**base, "market": "SECOND_HALF_TOTAL", "line": 20.5, "include_ot": False},
        {**base, "market": "SECOND_HALF_TOTAL", "line": 20.5, "include_ot": True},
        {**base, "market": "QUARTER_TOTAL", "line": 10.5, "quarter": 1},
        {**base, "market": "ALTERNATE_TOTAL", "line": 37.5},
        {**base, "market": "ALTERNATE_TOTAL", "line": 44.5},
        {**base, "market": "ALTERNATE_SPREAD", "line": -2.5},
        {**base, "market": "FIRST_HALF_TEAM_TOTAL", "side": "HOME", "team": home,
         "line": 10.5},
    ]


def empirical_team_total_check(rows, *, home_line: float, away_line: float) -> dict:
    """Identity check: pricer output vs the rows' own empirical fractions."""
    priced = price_nfl_team_totals(
        rows, home_total_line=home_line, away_total_line=away_line)
    n = float(len(rows))
    empirical = {
        "home_team_total": {
            "over": sum(r["home_score"] > home_line for r in rows) / n,
            "under": sum(r["home_score"] < home_line for r in rows) / n,
            "push": sum(r["home_score"] == home_line for r in rows) / n,
        },
        "away_team_total": {
            "over": sum(r["away_score"] > away_line for r in rows) / n,
            "under": sum(r["away_score"] < away_line for r in rows) / n,
            "push": sum(r["away_score"] == away_line for r in rows) / n,
        },
    }
    max_abs_diff = max(
        abs(priced[side][key] - empirical[side][key])
        for side in priced for key in priced[side])
    return {
        "pricer": priced, "empirical": empirical,
        "max_abs_diff": max_abs_diff,
        "identity_holds": max_abs_diff <= 1e-12,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default="DEN")
    parser.add_argument("--away", default="SEA")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=7)
    parser.add_argument("--n-sims", type=int, default=2000)
    parser.add_argument("--base-seed", type=int, default=20261015)
    parser.add_argument("--out", default=None,
                        help="write the JSON report here (default: stdout)")
    args = parser.parse_args(argv)

    source = load_frozen_profile_source()
    profiles = build_game_profiles(
        source, home_team=args.home, away_team=args.away,
        season=args.season, week=args.week)
    game_id = f"RESEARCH_{args.away}_{args.home}_{args.season}W{args.week:02d}"
    rows, manifest = simulate_joint_score_rows(
        profiles, game_id=game_id, n_sims=args.n_sims, base_seed=args.base_seed)
    intake = worked_example_intake(args.home, args.away)
    priced = price_research_derivatives(rows, manifest, intake_rows=intake)
    check = empirical_team_total_check(rows, home_line=19.5, away_line=20.5)

    report = {
        **RESEARCH_LABELS,
        "harness": "nfl_joint_score_research_harness",
        "distribution_manifest": manifest,
        "empirical_identity_check": check,
        "priced_derivatives": priced,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
