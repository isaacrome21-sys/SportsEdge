"""Research-only missing-route prioritization from DK menu census.

This is a routing gap report, not proof of DK offered quotes or model quality.
"""
from __future__ import annotations

from collections import Counter

from sportsedge.dk_canonical_reconciliation import reconcile_dk_census

PRIORITY = ("MLB", "NFL", "CFB", "NBA", "CBB")


def build_route_gap_report(census_path) -> dict:
    inventory = reconcile_dk_census(census_path)
    rows = inventory["rows"]
    by_sport = {}
    for sport in PRIORITY:
        sport_rows = [row for row in rows if row["sport"] == sport]
        counts = Counter(row["route_state"] for row in sport_rows)
        blockers = Counter(row["blocker"] for row in sport_rows if row["route_state"] != "PRICED_PATH")
        by_sport[sport] = {
            "menu_markets": len(sport_rows),
            "priced_path_not_validated": counts["PRICED_PATH"],
            "blocked": counts["BLOCKED"],
            "no_canonical_route": counts["NO_CANONICAL_ROUTE"],
            "blockers": dict(sorted((str(k), v) for k, v in blockers.items())),
            "inventory_missing": sport in inventory["missing_sport_census"],
        }
    gaps = [
        {"sport": row["sport"], "market": row["dk_market_key"],
         "blocker": row["blocker"], "route_state": row["route_state"]}
        for row in rows if row["route_state"] != "PRICED_PATH"
    ]
    gaps.sort(key=lambda row: (PRIORITY.index(row["sport"]),
                               0 if row["route_state"] == "NO_CANONICAL_ROUTE" else 1,
                               row["market"]))
    return {
        "schema": "SPORTSEDGE_DK_ROUTE_GAPS_V1",
        "authority": "RESEARCH_ONLY_NO_QUOTES_NO_PLAY",
        "by_sport": by_sport,
        "gaps": gaps,
        "missing_sport_census": inventory["missing_sport_census"],
        "play_authorized": False,
    }
