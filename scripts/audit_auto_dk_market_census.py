#!/usr/bin/env python3
"""Offline, fail-closed inventory of the automatic DK scanner's market-family gaps.

This is a *request coverage* audit, not a sportsbook-menu census or evidence
that any quote was obtained. It makes no API requests and grants no pricing,
model validation, bet logging or PLAY authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.collect_auto_dk_four_sports import MARKETS, SPORTS

# Owner's RUN IT coverage requirements (#2447). These are FAMILIES, not
# asserted provider keys or an authenticated DraftKings menu. Market names
# and exact offerings must be discovered and mapped in a separate reviewed
# intake step, subject to source access and quota.
REQUIRED_FAMILIES = {
    "NFL": ("moneyline", "spread", "total", "alternate_lines", "halves",
            "quarters", "team_totals", "player_props"),
    "CFB": ("moneyline", "spread", "total", "alternate_lines", "halves",
            "quarters", "team_totals", "player_props"),
    "MLB": ("moneyline", "run_line", "total", "alternate_lines", "first_five",
            "first_inning", "team_totals", "batter_props", "pitcher_props"),
    "NBA": ("moneyline", "spread", "total", "alternate_lines", "halves",
            "quarters", "team_totals", "player_props"),
    "NHL": ("moneyline", "puck_line", "total", "alternate_lines", "periods",
            "team_totals", "player_props"),
}

# Only whole-game base pairs are represented by these three V4 keys.
# A period or alternative line is NOT covered merely because its base
# market uses the same label.
BASE_GAME_KEYS = {
    "moneyline": "h2h",
    "spread": "spreads",
    "run_line": "spreads",
    "puck_line": "spreads",
    "total": "totals",
}


def audit(*, sports=None, markets=None):
    """Return honest coverage for the *configured request*, without IO."""
    requested_sports = dict(SPORTS if sports is None else sports)
    requested_markets = set(MARKETS if markets is None else markets)
    if not all(isinstance(s, str) for s in requested_sports):
        raise ValueError("AUTO_DK_SPORT_IDS_INVALID")
    if not all(isinstance(m, str) for m in requested_markets):
        raise ValueError("AUTO_DK_MARKET_IDS_INVALID")

    results = {}
    gaps = 0
    requested = 0
    for sport, required in REQUIRED_FAMILIES.items():
        sport_enabled = sport in requested_sports
        rows = []
        for family in required:
            base_key = BASE_GAME_KEYS.get(family)
            is_requested = sport_enabled and base_key in requested_markets
            status = ("REQUESTED_UNVERIFIED" if is_requested
                      else "SPORT_NOT_CONFIGURED" if not sport_enabled
                      else "FAMILY_NOT_REQUESTED")
            rows.append({"family": family, "request_market_key": base_key,
                         "status": status,
                         "quote_verified": False, "model_validated": False})
            requested += int(is_requested)
            gaps += int(not is_requested)
        results[sport] = {
            "sport_configured": sport_enabled,
            "family_count": len(rows),
            "requested_unverified": sum(
                row["status"] == "REQUESTED_UNVERIFIED" for row in rows),
            "not_requested": sum(
                row["status"] != "REQUESTED_UNVERIFIED" for row in rows),
            "families": rows,
        }

    return {
        "schema": "AUTO_DK_MARKET_FAMILY_REQUEST_COVERAGE_V1",
        "status": "INCOMPLETE" if gaps else "REQUESTS_PRESENT_UNVERIFIED",
        "source": "OWNER_REQUIRED_FAMILIES_NOT_PROVIDER_MENU",
        "provider_catalog_authenticated": False,
        "exact_dk_market_census_complete": False,
        "full_board_coverage_verified": False,
        "pricing_validated": False,
        "play_authority": False,
        "sport_keys_requested": sorted(requested_sports),
        "base_market_keys_requested": sorted(requested_markets),
        "required_family_count": sum(map(len, REQUIRED_FAMILIES.values())),
        "families_requested_but_unverified": requested,
        "families_not_requested": gaps,
        "sports": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional report path; no sportsbook/network access")
    args = parser.parse_args(argv)
    result = audit()
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    # Missing product scope is an honest report, not a CI error. The
    # acceptance gate must explicitly require full_board_coverage_verified.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
