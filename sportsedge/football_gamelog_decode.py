"""Fail-closed ESPN NFL/CFB gamelog stat-name decoding."""
from __future__ import annotations

from math import isfinite
from typing import Mapping

# Only unambiguous names. Generic YDS/ATT/TD may mean pass, rush or receiving.
FIELDS = {
    "passingyards": "passing_yards", "passingyds": "passing_yards",
    "passingtouchdowns": "passing_tds", "passingtds": "passing_tds",
    "passingattempts": "pass_attempts", "passattempts": "pass_attempts",
    "completions": "completions", "passingcompletions": "completions",
    "interceptions": "interceptions", "passinginterceptions": "interceptions",
    "rushingyards": "rushing_yards", "rushingyds": "rushing_yards",
    "rushingattempts": "rush_attempts", "rushattempts": "rush_attempts",
    "receivingyards": "receiving_yards", "receivingyds": "receiving_yards",
    "receptions": "receptions",
}

class FootballGamelogSchemaError(ValueError):
    pass

def _canon(name):
    return "".join(c for c in str(name).lower() if c.isalnum())

def _stat(value):
    if isinstance(value, bool):
        raise FootballGamelogSchemaError("STAT_INVALID")
    try:
        num = float(str(value).replace(",", ""))
    except (ValueError, TypeError, OverflowError) as exc:
        raise FootballGamelogSchemaError("STAT_NOT_NUMERIC") from exc
    if not isfinite(num):
        raise FootballGamelogSchemaError("STAT_NONFINITE")
    return num

def decode_football_event(gamelog: Mapping, event: Mapping) -> dict:
    """Only accept explicit names-to-values mapping; do not guess raw arrays."""
    if not isinstance(gamelog, Mapping) or not isinstance(event, Mapping):
        raise FootballGamelogSchemaError("GAMELOG_EVENT_NOT_OBJECT")
    stats = event.get("stats")
    if isinstance(stats, Mapping):
        pairs = list(stats.items())
    elif isinstance(stats, list):
        names = gamelog.get("names")
        if not isinstance(names, list) or len(names) != len(stats):
            raise FootballGamelogSchemaError("ESPN_GAMELOG_NAMES_STATS_UNALIGNED")
        if any(not isinstance(n, str) or not n for n in names):
            raise FootballGamelogSchemaError("ESPN_GAMELOG_STAT_NAME_INVALID")
        pairs = list(zip(names, stats))
    else:
        raise FootballGamelogSchemaError("ESPN_GAMELOG_STATS_NOT_NAMED")
    result = {}
    for name, value in pairs:
        field = FIELDS.get(_canon(name))
        if not field:
            continue
        if field in result:
            raise FootballGamelogSchemaError("DUPLICATE_ESPN_FOOTBALL_STAT:" + field)
        result[field] = _stat(value)
    if not result:
        raise FootballGamelogSchemaError("NO_EXPLICITLY_NAMED_PLAYER_STATS")
    return result
