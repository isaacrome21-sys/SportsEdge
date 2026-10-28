"""NFL usage + EPA current-form signals via nflverse (free, public).

Three nflverse-data release artifacts, all keyless GitHub downloads:

  1. Snap counts (release `snap_counts`, snap_counts_<season>.csv):
     per player-game offense/defense/special-teams snap percentages.
     Current-form use: a player's recent snap share is the cleanest
     public "role is growing/shrinking" signal for prop research.
  2. Weekly player stats (release `stats_player`,
     stats_player_week_<season>.csv): per player-week counting stats
     incl. targets and passing/rushing/receiving EPA totals. Current-
     form use: target share (player targets / team targets) and
     per-player EPA sums over a recent window.
  3. Play-by-play (release `pbp`, play_by_play_<season>.csv.gz, ~7MB
     gz for 2026): per-play EPA. Current-form use: team EPA/play split
     pass/rush and offensive/defensive success rate over recent weeks.

Verified live 2026-10-27: snap_counts_2026.csv sha256
0994bd2c1126e06fdae2e130f379736e311c12c7dd0300c5958d6b2d86cd4098;
stats_player_week_2026.csv sha256
c5b3b92a9e4258a48f84a78ade8b1d7f69b543367bba6bc0205e9d268ab11174;
play_by_play_2026.csv.gz sha256
30f31f1faf184be5a3014395c6830ed81ac5f60a03790e3e4a849dc020a70396
(2026 rows through week 7 at pull time).

POINT-IN-TIME RULE: every function takes `through_week` (last completed
week) and filters week <= through_week; NFL week numbers are the
season's own. PBP rows also carry game dates, but week filtering is the
declared as-of rule for this layer.

RESEARCH-ONLY: labeled context for the card info pack; never a model
input and never a price change by itself.
"""
from __future__ import annotations

from typing import Any

from .common import Opener, fetch_bytes, parse_csv_body, receipt_of, require_columns, to_float, to_int

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"

SNAP_COLUMNS = ["game_id", "season", "game_type", "week", "player", "team", "offense_pct"]
WEEK_STAT_COLUMNS = [
    "player_display_name",
    "team",
    "season",
    "week",
    "season_type",
    "targets",
    "passing_epa",
    "rushing_epa",
    "receiving_epa",
]
PBP_COLUMNS = ["week", "posteam", "defteam", "play_type", "epa", "success", "pass", "rush"]


def _fetch_csv(url: str, *, gzipped: bool, required: list[str], opener: Opener | None) -> dict[str, Any]:
    result = fetch_bytes(url, opener=opener)
    if result["status"] != "OK":
        return result
    try:
        rows = parse_csv_body(result["body"], gzipped=gzipped)
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    if not require_columns(rows, required):
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    return {"status": "OK", "receipt": receipt_of(result), "rows": rows}


def _through(rows: list[dict[str, str]], season: int, through_week: int) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if to_int(row.get("season")) == season
        and (week := to_int(row.get("week"))) is not None
        and 1 <= week <= through_week
    ]


def snap_share_form(
    *, season: int, through_week: int, last_n: int = 4, opener: Opener | None = None
) -> dict[str, Any]:
    """Per-player offensive snap-share: season mean vs last-N-games mean."""
    fetched = _fetch_csv(
        f"{RELEASE}/snap_counts/snap_counts_{season}.csv",
        gzipped=False,
        required=SNAP_COLUMNS,
        opener=opener,
    )
    if fetched["status"] != "OK":
        return fetched
    rows = [
        row for row in _through(fetched["rows"], season, through_week) if row.get("game_type") == "REG"
    ]
    players: dict[str, dict[str, Any]] = {}
    for name in sorted({row["player"] for row in rows}):
        mine = [row for row in rows if row["player"] == name]
        pcts = [pct for row in mine if (pct := to_float(row.get("offense_pct"))) is not None]
        if not pcts:
            continue
        recent = pcts[-last_n:]
        players[name] = {
            "team": mine[-1].get("team"),
            "games": len(pcts),
            "offense_pct_season": round(sum(pcts) / len(pcts), 4),
            "offense_pct_last_n": round(sum(recent) / len(recent), 4),
        }
    return {
        "status": "OK",
        "source": "nflverse snap_counts release",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season": season,
        "through_week": through_week,
        "receipt": fetched["receipt"],
        "players": players,
    }


def target_share_form(
    *, season: int, through_week: int, last_n: int = 4, opener: Opener | None = None
) -> dict[str, Any]:
    """Per-player target share + EPA sums: season vs last-N-weeks window.

    Target share = player targets / team targets in the same window.
    EPA fields are the source's per-week totals, summed over the window.
    """
    fetched = _fetch_csv(
        f"{RELEASE}/stats_player/stats_player_week_{season}.csv",
        gzipped=False,
        required=WEEK_STAT_COLUMNS,
        opener=opener,
    )
    if fetched["status"] != "OK":
        return fetched
    rows = [
        row for row in _through(fetched["rows"], season, through_week) if row.get("season_type") == "REG"
    ]

    def summarize(window: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        team_targets: dict[str, float] = {}
        for row in window:
            team_targets[row["team"]] = team_targets.get(row["team"], 0.0) + (
                to_float(row.get("targets")) or 0.0
            )
        out: dict[str, dict[str, Any]] = {}
        for name in sorted({row["player_display_name"] for row in window}):
            mine = [row for row in window if row["player_display_name"] == name]
            team = mine[-1]["team"]
            targets = sum(to_float(row.get("targets")) or 0.0 for row in mine)
            out[name] = {
                "team": team,
                "targets": targets,
                "target_share": round(targets / team_targets[team], 4) if team_targets.get(team) else None,
                "passing_epa": round(sum(to_float(row.get("passing_epa")) or 0.0 for row in mine), 3),
                "rushing_epa": round(sum(to_float(row.get("rushing_epa")) or 0.0 for row in mine), 3),
                "receiving_epa": round(sum(to_float(row.get("receiving_epa")) or 0.0 for row in mine), 3),
            }
        return out

    weeks = sorted({week for row in rows if (week := to_int(row["week"])) is not None})
    recent = [row for row in rows if to_int(row["week"]) in set(weeks[-last_n:])]
    return {
        "status": "OK",
        "source": "nflverse stats_player weekly release",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season": season,
        "through_week": through_week,
        "receipt": fetched["receipt"],
        "players_season": summarize(rows),
        "players_last_n": summarize(recent),
    }


def team_epa_form(
    *, season: int, through_week: int, last_n: int = 4, opener: Opener | None = None
) -> dict[str, Any]:
    """Team EPA/play (pass/rush splits) + success rate, season vs last-N.

    Defensive view = EPA/play allowed (same plays, grouped by defteam;
    lower is better defense). Only plays with a recorded EPA and a
    pass/rush flag count; no-play/penalty rows are excluded by the
    source's own flags.
    """
    fetched = _fetch_csv(
        f"{RELEASE}/pbp/play_by_play_{season}.csv.gz",
        gzipped=True,
        required=PBP_COLUMNS,
        opener=opener,
    )
    if fetched["status"] != "OK":
        return fetched
    rows = [
        row
        for row in fetched["rows"]
        if (week := to_int(row.get("week"))) is not None and 1 <= week <= through_week
    ]

    def aggregate(window: list[dict[str, str]], key: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, float]] = {}
        for row in window:
            epa = to_float(row.get("epa"))
            team = row.get(key)
            if epa is None or not team:
                continue
            bucket = buckets.setdefault(
                team, {"plays": 0, "epa": 0.0, "pass_plays": 0, "pass_epa": 0.0,
                       "rush_plays": 0, "rush_epa": 0.0, "success": 0.0}
            )
            bucket["plays"] += 1
            bucket["epa"] += epa
            bucket["success"] += to_float(row.get("success")) or 0.0
            if row.get("pass") == "1":
                bucket["pass_plays"] += 1
                bucket["pass_epa"] += epa
            elif row.get("rush") == "1":
                bucket["rush_plays"] += 1
                bucket["rush_epa"] += epa
        out: dict[str, dict[str, Any]] = {}
        for team, bucket in sorted(buckets.items()):
            plays = bucket["plays"]
            out[team] = {
                "plays": int(plays),
                "epa_per_play": round(bucket["epa"] / plays, 4) if plays else None,
                "pass_epa_per_play": round(bucket["pass_epa"] / bucket["pass_plays"], 4)
                if bucket["pass_plays"]
                else None,
                "rush_epa_per_play": round(bucket["rush_epa"] / bucket["rush_plays"], 4)
                if bucket["rush_plays"]
                else None,
                "success_rate": round(bucket["success"] / plays, 4) if plays else None,
            }
        return out

    weeks = sorted({week for row in rows if (week := to_int(row["week"])) is not None})
    recent = [row for row in rows if to_int(row["week"]) in set(weeks[-last_n:])]
    return {
        "status": "OK",
        "source": "nflverse play-by-play release (EPA)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season": season,
        "through_week": through_week,
        "receipt": fetched["receipt"],
        "offense_season": aggregate(rows, "posteam"),
        "offense_last_n": aggregate(recent, "posteam"),
        "defense_season": aggregate(rows, "defteam"),
        "defense_last_n": aggregate(recent, "defteam"),
    }
