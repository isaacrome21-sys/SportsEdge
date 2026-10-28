"""NFL Next Gen Stats current-form signals via nflverse (free, public).

Source: nflverse-data GitHub release `nextgen_stats` -- the consolidated
per-stat-type CSVs (ngs_passing.csv.gz / ngs_rushing.csv.gz /
ngs_receiving.csv.gz) that aggregate every season including the current
one, refreshed by nflverse during the season. These are the same files
nflreadr::load_nextgen_stats() reads. NFL's own NGS site is a JS app;
nflverse is the machine-readable free path. No key, no account.

Verified live 2026-10-27 (America/Chicago): consolidated passing file
sha256 6341543f68fb196baca61dbac145468901be607e2d9c50f588c22b99d8a96c54,
contains seasons through 2026, with 2026 REG rows through week 7 (the
last completed week at pull time).

POINT-IN-TIME RULE: rows carry season/season_type/week. Callers pass
`through_week` = the last COMPLETED week before the game being priced.
Week 0 rows are nflverse's season-aggregate rows and are always excluded
from weekly windows. The leak risk is caller error (passing a future
through_week), so the function refuses a through_week beyond the max
week present in the file for that season and reports the file's actual
max week.

RESEARCH-ONLY: outputs are labeled context for the card info pack.
They never enter a model or move a price by themselves (see the
factoring spec in research/analytics_current_form_20261027/).
"""
from __future__ import annotations

from typing import Any

from .common import Opener, fetch_bytes, parse_csv_body, receipt_of, require_columns, to_float, to_int

NGS_RELEASE = "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats"
STAT_TYPES = ("passing", "rushing", "receiving")

# Whitelisted current-form metrics per stat type (weekly values in the
# source). The volume column weights the window means so a one-attempt
# week cannot dominate a player's recent form.
METRICS: dict[str, dict[str, Any]] = {
    "passing": {
        "volume": "attempts",
        "metrics": [
            "completion_percentage_above_expectation",
            "avg_time_to_throw",
            "avg_intended_air_yards",
            "avg_air_yards_to_sticks",
            "aggressiveness",
            "passer_rating",
        ],
    },
    "rushing": {
        "volume": "rush_attempts",
        "metrics": [
            "rush_yards_over_expected_per_att",
            "rush_pct_over_expected",
            "efficiency",
            "percent_attempts_gte_eight_defenders",
            "avg_time_to_los",
        ],
    },
    "receiving": {
        "volume": "targets",
        "metrics": [
            "avg_separation",
            "avg_cushion",
            "avg_yac_above_expectation",
            "percent_share_of_intended_air_yards",
            "catch_percentage",
        ],
    },
}

CORE_COLUMNS = ["season", "season_type", "week", "player_display_name", "team_abbr"]


def fetch_ngs(stat_type: str, *, opener: Opener | None = None) -> dict[str, Any]:
    """Fetch and parse one consolidated NGS file. Fail-closed."""
    if stat_type not in STAT_TYPES:
        return {"status": "MISSING", "reason": "NGS_UNKNOWN_STAT_TYPE"}
    result = fetch_bytes(f"{NGS_RELEASE}/ngs_{stat_type}.csv.gz", opener=opener)
    if result["status"] != "OK":
        return result
    try:
        rows = parse_csv_body(result["body"], gzipped=True)
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    required = CORE_COLUMNS + [METRICS[stat_type]["volume"], *METRICS[stat_type]["metrics"]]
    if not require_columns(rows, required):
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    return {"status": "OK", "receipt": receipt_of(result), "rows": rows}


def _window(
    rows: list[dict[str, str]], season: int, through_week: int, last_n: int | None
) -> list[dict[str, str]]:
    weekly = [
        row
        for row in rows
        if to_int(row.get("season")) == season
        and row.get("season_type") == "REG"
        and (week := to_int(row.get("week"))) is not None
        and 1 <= week <= through_week
    ]
    if last_n is None:
        return weekly
    weeks = sorted({week for row in weekly if (week := to_int(row["week"])) is not None})
    keep = set(weeks[-last_n:])
    return [row for row in weekly if to_int(row["week"]) in keep]


def _weighted_mean(rows: list[dict[str, str]], metric: str, volume_column: str) -> float | None:
    total_weight = 0.0
    total = 0.0
    for row in rows:
        value = to_float(row.get(metric))
        weight = to_float(row.get(volume_column)) or 0.0
        if value is None or weight <= 0:
            continue
        total += value * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return round(total / total_weight, 4)


def current_form_ngs(
    stat_type: str,
    *,
    season: int,
    through_week: int,
    last_n: int = 4,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """Per-player season-to-date and last-N-weeks NGS form for one season.

    Returns {"status": "OK", "source", "label": "RESEARCH_CONTEXT_ONLY",
    "season", "through_week", "file_max_week", "receipt",
    "players": {name: {"team", "season": {...}, "last_n": {...},
    "weeks": [...]}}}. Fails closed if the requested through_week
    exceeds the file's actual max week (stale-file guard).
    """
    fetched = fetch_ngs(stat_type, opener=opener)
    if fetched["status"] != "OK":
        return fetched
    rows = fetched["rows"]
    season_weeks = [
        week
        for row in rows
        if to_int(row.get("season")) == season
        and row.get("season_type") == "REG"
        and (week := to_int(row.get("week"))) is not None
        and week >= 1
    ]
    if not season_weeks:
        return {"status": "MISSING", "reason": "NGS_SEASON_ABSENT", "receipt": fetched["receipt"]}
    file_max_week = max(season_weeks)
    if through_week > file_max_week:
        return {
            "status": "MISSING",
            "reason": "NGS_THROUGH_WEEK_BEYOND_FILE",
            "file_max_week": file_max_week,
            "receipt": fetched["receipt"],
        }
    spec = METRICS[stat_type]
    players: dict[str, dict[str, Any]] = {}
    season_window = _window(rows, season, through_week, None)
    names = sorted({row["player_display_name"] for row in season_window})
    for name in names:
        player_rows = [row for row in rows if row["player_display_name"] == name]
        season_rows = _window(player_rows, season, through_week, None)
        recent_rows = _window(player_rows, season, through_week, last_n)
        if not season_rows:
            continue
        players[name] = {
            "team": season_rows[-1].get("team_abbr"),
            "season": {m: _weighted_mean(season_rows, m, spec["volume"]) for m in spec["metrics"]},
            "last_n": {m: _weighted_mean(recent_rows, m, spec["volume"]) for m in spec["metrics"]},
            "weeks": sorted({week for row in season_rows if (week := to_int(row["week"])) is not None}),
        }
    return {
        "status": "OK",
        "source": "NFL Next Gen Stats via nflverse (nextgen_stats release)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season": season,
        "through_week": through_week,
        "file_max_week": file_max_week,
        "receipt": fetched["receipt"],
        "players": players,
    }
