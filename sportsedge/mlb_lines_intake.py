"""Turn MLB lines typed on a phone into the canonical manual-input contract.

This is transcription only. It resolves games against the MLB schedule and maps
human-friendly line labels to existing SportsEdge manual market types. It never
creates or changes a probability.

Every row requires both offered prices. The issue open/edit timestamp is retained
as ``INTAKE_STAMPED`` provenance and is explicitly not a sportsbook timestamp.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .mlb_source import GameSnapshot, parse_game_start


class LinesIntakeError(ValueError):
    pass


_PRICE = r"([+-]?\d{3,5}|EVEN|EV)"
_NUM = r"(\d+(?:\.\d+)?)"
_SIGNED_NUM = r"([+-]?\d+(?:\.\d+)?)"

# Ambiguous bare K/strikeouts is intentionally pitcher-oriented, matching the
# common sportsbook shorthand. Batter strikeouts require an explicit batter tag.
_PLAYER_STATS = {
    "outs": "PITCHER_OUTS",
    "outs recorded": "PITCHER_OUTS",
    "k": "PITCHER_STRIKEOUTS",
    "ks": "PITCHER_STRIKEOUTS",
    "strikeouts": "PITCHER_STRIKEOUTS",
    "pitcher k": "PITCHER_STRIKEOUTS",
    "pitcher ks": "PITCHER_STRIKEOUTS",
    "hits allowed": "PITCHER_HITS_ALLOWED",
    "pitcher hits": "PITCHER_HITS_ALLOWED",
    "walks allowed": "PITCHER_WALKS",
    "pitcher walks": "PITCHER_WALKS",
    "er": "PITCHER_EARNED_RUNS",
    "earned runs": "PITCHER_EARNED_RUNS",
    "hits walks er": "PITCHER_HITS_WALKS_ER",
    "hits+walks+er": "PITCHER_HITS_WALKS_ER",
    "h+bb+er": "PITCHER_HITS_WALKS_ER",
    "hits": "BATTER_HITS",
    "tb": "BATTER_TOTAL_BASES",
    "total bases": "BATTER_TOTAL_BASES",
    "hr": "BATTER_HOME_RUNS",
    "home run": "BATTER_HOME_RUNS",
    "home runs": "BATTER_HOME_RUNS",
    "rbi": "BATTER_RBI",
    "rbis": "BATTER_RBI",
    "runs": "BATTER_RUNS",
    "sb": "BATTER_STOLEN_BASES",
    "stolen bases": "BATTER_STOLEN_BASES",
    "bb": "BATTER_WALKS",
    "walks": "BATTER_WALKS",
    "xbh": "EXTRA_BASE_HITS",
    "extra base hits": "EXTRA_BASE_HITS",
    "singles": "SINGLES",
    "doubles": "DOUBLES",
    "triples": "TRIPLES",
    "batter k": "BATTER_STRIKEOUTS",
    "batter ks": "BATTER_STRIKEOUTS",
    "batter strikeouts": "BATTER_STRIKEOUTS",
    "hrr": "HITS_RUNS_RBIS",
    "h+r+rbi": "HITS_RUNS_RBIS",
    "hits+runs+rbi": "HITS_RUNS_RBIS",
    "h+r+sb": "HITS_RUNS_STOLEN_BASES",
    "hits+runs+sb": "HITS_RUNS_STOLEN_BASES",
    "r+rbi": "RUNS_RBIS",
    "runs+rbi": "HITS_RUNS_RBIS",
    "h+sb": "HITS_STOLEN_BASES",
    "hits+sb": "HITS_STOLEN_BASES",
    "h+bb+sb": "HITS_WALKS_STOLEN_BASES",
    "hits+walks+sb": "HITS_WALKS_STOLEN_BASES",
}
