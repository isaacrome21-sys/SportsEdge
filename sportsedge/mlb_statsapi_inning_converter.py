"""Convert *locally supplied* MLB StatsAPI game feeds to inning evidence.

Does not download games. Caller supplies each unmodified final-game feed
and a source URL; a timestamped evidence manifest is mandatory.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from sportsedge.mlb_period_counts_empirical import _instant


def convert_final_game_feed(feed: Mapping) -> dict:
    data = feed.get("gameData")
    live = feed.get("liveData")
    if not isinstance(data, dict) or not isinstance(live, dict):
        raise ValueError("MISSING_GAME_FEED")
    game = data.get("game", {})
    game_id = game.get("pk")
    if not isinstance(game_id, int) or isinstance(game_id, bool) or game_id <= 0:
        raise ValueError("MISSING_GAME_PK")
    status = data.get("status", {})
    if status.get("abstractGameState") != "Final":
        raise ValueError("GAME_NOT_FINAL")
    when = data.get("datetime", {}).get("dateTime")
    _instant(when)
    innings = live.get("linescore", {}).get("innings")
    if not isinstance(innings, list) or len(innings) < 9:
        raise ValueError("INCOMPLETE_INNINGS")
    runs = []
    for idx, inning in enumerate(innings, start=1):
        if not isinstance(inning, dict) or inning.get("num") != idx:
            raise ValueError("NONCONTIGUOUS_INNINGS")
        away = inning.get("away", {}).get("runs")
        home = inning.get("home", {}).get("runs")
        if not isinstance(away, int) or isinstance(away, bool) or away < 0:
            raise ValueError("MISSING_AWAY_RUNS")
        if home is None:
            # Bottom of the final inning may be unplayed when home leads.
            # This must be supported by the final linescore and winning score.
            linescore = live["linescore"]
            teams = linescore.get("teams", {})
            home_total = teams.get("home", {}).get("runs")
            away_total = teams.get("away", {}).get("runs")
            if (idx != len(innings) or not isinstance(home_total, int)
                    or not isinstance(away_total, int) or home_total <= away_total):
                raise ValueError("UNVERIFIED_UNPLAYED_HOME_HALF")
            home = 0
        if not isinstance(home, int) or isinstance(home, bool) or home < 0:
            raise ValueError("MISSING_HOME_RUNS")
        runs.append(away + home)
    teams = live["linescore"].get("teams", {})
    htotal = teams.get("home", {}).get("runs")
    atotal = teams.get("away", {}).get("runs")
    if (not isinstance(htotal, int) or isinstance(htotal, bool) or htotal < 0
            or not isinstance(atotal, int) or isinstance(atotal, bool) or atotal < 0
            or sum(runs) != htotal + atotal):
        raise ValueError("INNING_TOTAL_MISMATCH")
    if htotal == atotal:
        raise ValueError("FINAL_GAME_TIED")
    # Inning-level totals must also reconcile independently by side. A
    # swapped home/away run can preserve combined totals and hide corruption.
    away_sum = sum(inning["away"]["runs"] for inning in innings)
    home_sum = sum((inning["home"]["runs"] or 0) for inning in innings)
    if away_sum != atotal or home_sum != htotal:
        raise ValueError("SIDE_INNING_TOTAL_MISMATCH")
    return {"game_id": str(game_id), "start_time": when, "inning_runs": runs}


def make_historical_export(
    feeds: Sequence[Mapping], *, source_url: str, observed_at: str,
) -> dict:
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise ValueError("INVALID_SOURCE_URL")
    observed = _instant(observed_at)
    if not feeds:
        raise ValueError("EMPTY_FEEDS")
    games = []
    seen = set()
    for feed in feeds:
        row = convert_final_game_feed(feed)
        if row["game_id"] in seen:
            raise ValueError("DUPLICATE_GAME_ID")
        seen.add(row["game_id"])
        if _instant(row["start_time"]) > observed:
            raise ValueError("GAME_AFTER_OBSERVATION")
        games.append(row)
    return {
        "schema": "MLB_HISTORICAL_INNING_EXPORT_V1",
        "source_url": source_url,
        "observed_at": observed_at,
        "games": games,
    }
