"""Fail-closed ESPN NBA gamelog stat decoding.

Verified live 2026-10-11 against
https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog

Actual shape (differs from the site.api v2 gamelog path, which 404s for NBA):
  - top-level ``events`` is a DICT keyed by eventId (not a list)
  - per-game player stats live in ``seasonTypes[].categories[]`` entries with
    ``type == "event"`` as ``{"eventId", "stats": [strings]}``
  - ``stats`` columns align positionally with top-level ``names``
  - categories with ``type == "total"`` are summaries and are never games
  - per-event metadata (gameDate, atVs, team, opponent, scores) lives in the
    ``events`` dict entry for the eventId

Only unambiguous stat names are decoded. Anything else fails closed.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping


class NBAGamelogSchemaError(ValueError):
    pass


def _canon(name) -> str:
    return "".join(c for c in str(name).lower() if c.isalnum())


# canonical ESPN ``names`` entry -> our field. Minutes are whole numbers in
# the gamelog ("29"); made/attempted pairs ("6-11") decode to made.
FIELDS = {
    "minutes": "minutes",
    "points": "points",
    "totalrebounds": "rebounds",
    "assists": "assists",
    "threepointfieldgoalsmadethreepointfieldgoalsattempted": "threes_made",
    "blocks": "blocks",
    "steals": "steals",
    "fouls": "fouls",
    "turnovers": "turnovers",
}

REQUIRED_FIELDS = frozenset({"minutes", "points", "rebounds", "assists", "threes_made"})


def _number(value, *, field: str):
    if isinstance(value, bool):
        raise NBAGamelogSchemaError("STAT_INVALID:" + field)
    try:
        num = float(str(value).replace(",", ""))
    except (ValueError, TypeError, OverflowError) as exc:
        raise NBAGamelogSchemaError("STAT_NOT_NUMERIC:" + field) from exc
    if not isfinite(num):
        raise NBAGamelogSchemaError("STAT_NONFINITE:" + field)
    return num


def _made(value, *, field: str) -> int:
    """Decode a 'made-attempted' pair like '4-9' to made (int)."""
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) != 2:
        raise NBAGamelogSchemaError("STAT_PAIR_MALFORMED:" + field)
    made = _number(parts[0], field=field)
    attempted = _number(parts[1], field=field)
    if made < 0 or attempted < 0 or made > attempted:
        raise NBAGamelogSchemaError("STAT_PAIR_INCONSISTENT:" + field)
    if made != int(made):
        raise NBAGamelogSchemaError("STAT_PAIR_NONINTEGER:" + field)
    return int(made)


def _named_pairs(gamelog: Mapping, stats: list) -> list:
    names = gamelog.get("names")
    if not isinstance(names, list) or len(names) != len(stats):
        raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_NAMES_STATS_UNALIGNED")
    if any(not isinstance(n, str) or not n for n in names):
        raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_STAT_NAME_INVALID")
    return list(zip(names, stats))


def decode_nba_gamelog_event(gamelog: Mapping, category_event: Mapping) -> dict:
    """Decode one ``{"eventId", "stats"}`` entry to explicit stat fields.

    Returns {"minutes", "points", "rebounds", "assists", "threes_made",
    "blocks", "steals", "fouls", "turnovers"} as numbers/ints. Raises
    NBAGamelogSchemaError on any unverified shape.
    """
    if not isinstance(gamelog, Mapping) or not isinstance(category_event, Mapping):
        raise NBAGamelogSchemaError("GAMELOG_EVENT_NOT_OBJECT")
    event_id = str(category_event.get("eventId") or "").strip()
    if not event_id:
        raise NBAGamelogSchemaError("PRIOR_GAME_ID_UNVERIFIED")
    stats = category_event.get("stats")
    if not isinstance(stats, list) or not stats:
        raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_STATS_NOT_LIST:" + event_id)

    result: dict = {}
    for name, value in _named_pairs(gamelog, stats):
        field = FIELDS.get(_canon(name))
        if not field:
            continue
        if field in result:
            raise NBAGamelogSchemaError("DUPLICATE_ESPN_NBA_STAT:" + field)
        if field == "threes_made":
            result[field] = _made(value, field=field)
        else:
            result[field] = _number(value, field=field)

    missing = REQUIRED_FIELDS - set(result)
    if missing:
        raise NBAGamelogSchemaError(
            "NBA_REQUIRED_STATS_MISSING:" + ",".join(sorted(missing)))
    minutes = result["minutes"]
    if not 0 <= minutes <= 53:
        raise NBAGamelogSchemaError("NBA_MINUTES_OUT_OF_RANGE")
    for key in ("points", "rebounds", "assists", "threes_made"):
        if result[key] < 0:
            raise NBAGamelogSchemaError("NBA_STAT_NEGATIVE:" + key)
    result["event_id"] = event_id
    return result


def iter_gamelog_games(gamelog: Mapping):
    """Yield (season_type_display, event_meta, category_event) for each real game.

    Skips ``type == "total"`` summary categories. Fails closed on unverified
    shapes. ``event_meta`` is the ``events`` dict entry for the eventId.
    """
    if not isinstance(gamelog, Mapping):
        raise NBAGamelogSchemaError("GAMELOG_NOT_OBJECT")
    events = gamelog.get("events")
    if not isinstance(events, dict):
        raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_EVENTS_NOT_DICT")
    season_types = gamelog.get("seasonTypes")
    if not isinstance(season_types, list):
        raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_SEASONTYPES_NOT_LIST")
    for season_type in season_types:
        if not isinstance(season_type, dict):
            raise NBAGamelogSchemaError("ESPN_NBA_SEASONTYPE_NOT_OBJECT")
        st_display = str(season_type.get("displayName") or "")
        categories = season_type.get("categories")
        if not isinstance(categories, list):
            raise NBAGamelogSchemaError("ESPN_NBA_GAMELOG_CATEGORIES_NOT_LIST")
        for category in categories:
            if not isinstance(category, dict):
                raise NBAGamelogSchemaError("ESPN_NBA_CATEGORY_NOT_OBJECT")
            if category.get("type") != "event":
                continue  # summary totals are not games
            cat_events = category.get("events")
            if not isinstance(cat_events, list):
                raise NBAGamelogSchemaError("ESPN_NBA_CATEGORY_EVENTS_NOT_LIST")
            for cat_event in cat_events:
                if not isinstance(cat_event, dict):
                    raise NBAGamelogSchemaError("ESPN_NBA_CATEGORY_EVENT_NOT_OBJECT")
                event_id = str(cat_event.get("eventId") or "").strip()
                if not event_id or event_id not in events:
                    raise NBAGamelogSchemaError(
                        "ESPN_NBA_EVENT_META_MISSING:" + (event_id or "?"))
                meta = events[event_id]
                if not isinstance(meta, dict):
                    raise NBAGamelogSchemaError("ESPN_NBA_EVENT_META_NOT_OBJECT")
                yield st_display, meta, cat_event
