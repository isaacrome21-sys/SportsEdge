"""Tracking-data source investigation registry (Phase 3, 2026-10-11).

Endpoint-by-endpoint verdicts under Isaac's standing bar: a source is WIRED
only when it is free AND stable AND verifiable. Anything else is NOT_WIRED
with an explicit reason code. "Stable" here means a documented contract or an
officially documented API family -- undocumented endpoints are never built
upon, no matter how long they have worked.

Reason codes:
  UNDOCUMENTED_ENDPOINT          no official docs; may change/vanish unannounced
  ENDPOINT_UNREACHABLE           probed and unreachable / non-functional
  API_KEY_REQUIRED               free tier exists but needs a provisioned key
  NO_PUBLIC_SOURCE_EXISTS        no free public source for this data, period
  OUT_OF_SCOPE_DEFERRED          documented and available; not tracking data,
                                 deferred to its own phase
  LEGACY_GRANDFATHERED           predates the strict bar; kept, not expanded
"""
from __future__ import annotations

from typing import Any

REGISTRY_VERSION = "tracking_source_registry_v1"

WIRED = "WIRED"
NOT_WIRED = "NOT_WIRED"

TRACKING_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "MLB_STATSAPI_PITCH_TRACKING",
        "name": "MLB StatsAPI game feed pitch tracking",
        "endpoint": "https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live",
        "verdict": WIRED,
        "module": "sportsedge.mlb_statsapi_pitch_tracking",
        "evidence": (
            "Probed 2026-10-11: 2026-10-10 game (gamePk 849831) returned 257/257 "
            "pitch events with pitchData (startSpeed/endSpeed, spinRate, break "
            "shape, extension, coordinates); 2023-06-15 game (gamePk 717753) "
            "returned 278/278 -- multi-year history available. Official API "
            "docs hosted at statsapi.mlb.com/docs; same API family already "
            "wired for schedule/history. No auth, no key. `fields` filter "
            "slims payload ~700KB -> ~16KB."
        ),
        "fields": [
            "startSpeed", "endSpeed", "spinRate", "spinDirection",
            "breakAngle", "breakLength", "breakY", "breakHorizontal",
            "breakVertical", "extension", "plateTime", "typeConfidence",
            "zone", "pitch trajectory coordinates",
        ],
        "limits": [
            "Final games only (fail-closed); live/in-progress belongs to the live phase.",
            "Per-game fetch; building multi-season pitcher histories needs one call per game.",
            "Not yet a pricing factor -- must pass the backtest bar before any use in pricing.",
        ],
    },
    {
        "id": "NFLVERSE_NGS",
        "name": "nflverse Next Gen Stats releases",
        "endpoint": "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{passing|rushing|receiving}.csv.gz",
        "verdict": WIRED,
        "module": "sportsedge.nflverse_ngs",
        "evidence": (
            "Probed 2026-10-11: release tag `nextgen_stats` refreshed "
            "2026-10-11 (nightly in-season); seasons 2016--2026; 2026 weeks 0--5 "
            "present; 6,103 passing rows. Documented data dictionary in "
            "nflreadr (dictionary_nextgen_stats). Plain csv.gz assets exist -- "
            "no new dependency. Same release-tag pattern nflreadr has used since 2022."
        ),
        "fields": [
            "passing: avg_time_to_throw, avg_completed_air_yards, "
            "avg_intended_air_yards, aggressiveness, expected_completion_percentage, "
            "completion_percentage_above_expectation, ...",
            "rushing/receiving: documented metric sets per data dictionary.",
        ],
        "limits": [
            "Week-level granularity only (no play-level tracking).",
            "Players below minimum attempt thresholds are absent by design.",
            "Not yet a pricing factor -- must pass the backtest bar before any use in pricing.",
        ],
    },
    {
        "id": "BASEBALL_SAVANT_STATCAST_CSV",
        "name": "Baseball Savant statcast_search/csv",
        "endpoint": "https://baseballsavant.mlb.com/statcast_search/csv",
        "verdict": WIRED,
        "reason_code": "LEGACY_GRANDFATHERED",
        "module": "sportsedge.statcast_daily_source",
        "evidence": (
            "Probed 2026-10-11: alive (200, 1-day window returned pitch rows). "
            "UNDOCUMENTED: no official API docs; de-facto stability comes only "
            "from the pybaseball ecosystem. Already wired in main by earlier "
            "work (statcast_daily_source, consumed by mlb_pitcher_k_historical_* "
            "and mlb_run_it_pregame). Under the strict bar it would be "
            "NOT_WIRED/UNDOCUMENTED_ENDPOINT; it is grandfathered, not expanded. "
            "New Statcast-flavored acquisition must use MLB_STATSAPI_PITCH_TRACKING."
        ),
        "limits": ["Do not build new consumers on this endpoint."],
    },
    {
        "id": "NFL_NGS_OFFICIAL_API",
        "name": "Official NFL Next Gen Stats API",
        "endpoint": "https://api.nextgenstats.nfl.com/...",
        "verdict": NOT_WIRED,
        "reason_code": "UNDOCUMENTED_ENDPOINT",
        "evidence": (
            "Probed 2026-10-11: host unreachable from probe environment; no "
            "official public documentation exists. Historically schema-unstable "
            "and aggressively rate-limited. nflverse's republished release is "
            "the verifiable path instead (NFLVERSE_NGS)."
        ),
    },
    {
        "id": "ESPN_ADVANCED_METRICS",
        "name": "ESPN advanced metrics endpoints (QBR et al.)",
        "endpoint": "https://site.api.espn.com/apis/site/v2/sports/...",
        "verdict": NOT_WIRED,
        "reason_code": "UNDOCUMENTED_ENDPOINT",
        "evidence": (
            "Probed 2026-10-11: ESPN publishes no public API documentation; "
            "endpoint shapes are reverse-engineered and change without notice. "
            "Schedule/scoreboard endpoints are grandfathered by long stable use, "
            "but advanced-metrics surfaces are not built upon."
        ),
    },
    {
        "id": "CFB_PLAYER_TRACKING",
        "name": "CFB player tracking (Next Gen Stats equivalent)",
        "endpoint": None,
        "verdict": NOT_WIRED,
        "reason_code": "NO_PUBLIC_SOURCE_EXISTS",
        "evidence": (
            "Investigated 2026-10-11: no free public player-tracking feed "
            "exists for college football (no CFB equivalent of NFL NGS or MLB "
            "Statcast is published). Nothing to wire."
        ),
    },
    {
        "id": "CFBD_ADVANCED_STATS",
        "name": "CollegeFootballData advanced stats",
        "endpoint": "https://api.collegefootballdata.com/...",
        "verdict": NOT_WIRED,
        "reason_code": "API_KEY_REQUIRED",
        "evidence": (
            "Documented OpenAPI; free tier requires a provisioned API key "
            "(CFBD_API_KEY), which is not available in this environment, so the "
            "payloads could not be verified. Already wired for lines elsewhere "
            "(cfbd_cfb_market_context). Team-level advanced stats only -- no "
            "player tracking. Revisit when a key is provisioned; still not "
            "tracking data."
        ),
    },
    {
        "id": "NFLVERSE_NON_TRACKING",
        "name": "nflverse non-tracking datasets",
        "endpoint": "https://github.com/nflverse/nflverse-data/releases",
        "verdict": NOT_WIRED,
        "reason_code": "OUT_OF_SCOPE_DEFERRED",
        "evidence": (
            "Documented, free, same stable release pattern: snap_counts, "
            "injuries, depth_charts, rosters, player_stats, officials. "
            "Valuable free gaps but not tracking data; deferred to the "
            "free-factors phase where each is gated by the backtest bar."
        ),
    },
)


def verdict_for(source_id: str) -> dict[str, Any]:
    for entry in TRACKING_SOURCES:
        if entry["id"] == source_id:
            return dict(entry)
    raise KeyError(f"TRACKING_SOURCE_UNKNOWN:{source_id}")


def wired_sources() -> list[dict[str, Any]]:
    return [dict(e) for e in TRACKING_SOURCES if e["verdict"] == WIRED]


def not_wired_sources() -> list[dict[str, Any]]:
    return [dict(e) for e in TRACKING_SOURCES if e["verdict"] == NOT_WIRED]
