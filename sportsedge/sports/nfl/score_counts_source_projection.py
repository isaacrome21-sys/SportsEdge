"""Explicit market-blind projection for frozen NFL_SCORE_COUNTS_G1 PBP rows.

The frozen nflverse PBP bytes contain sportsbook-adjacent columns such as
spread_line and total_line.  Those raw columns are allowed to exist in the
immutable source object, but they are never allowed to enter the score-count
feature builder.  This module is the single allowlist boundary used by the
zero-attempt source preflight and the governed attempt runner.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

PBP_ALLOWED_FIELDS = (
    "game_id",
    "nflverse_game_id",
    "play_id",
    "no_play",
    "two_point_attempt",
    "qb_kneel",
    "qb_spike",
    "qb_dropback",
    "pass",
    "rush_attempt",
    "rush",
    "posteam",
    "possession_team",
    "defteam",
    "epa",
    "success",
    "sack",
    "passer_player_id",
    "passer_id",
    "qb_epa",
    "cpoe",
    "interception",
    "fumble_lost",
    "touchdown",
    "td_team",
    "return_touchdown",
    "field_goal_result",
    "extra_point_result",
    "two_point_conv_result",
    "safety",
)

_MARKET_TOKENS = (
    "odds",
    "price",
    "sportsbook",
    "market",
    "spread_line",
    "total_line",
    "closing",
    "opening",
    "implied",
    "vig",
    "handle",
    "tickets",
)


def project_pbp_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {name: row.get(name) for name in PBP_ALLOWED_FIELDS if name in row}
    bad = [name for name in out if any(token in name.lower() for token in _MARKET_TOKENS)]
    if bad:
        raise ValueError("NFL_SCORE_COUNTS_PBP_PROJECTION_MARKET_FIELD:" + ",".join(sorted(bad)))
    return out


def project_pbp_rows(rows: Iterable[Mapping[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        yield project_pbp_row(row)


__all__ = ["PBP_ALLOWED_FIELDS", "project_pbp_row", "project_pbp_rows"]
