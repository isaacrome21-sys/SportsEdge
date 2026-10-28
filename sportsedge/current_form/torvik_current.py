"""BartTorvik current player advanced stats (thin current-form fetcher).

COORDINATION: BartTorvik TEAM ratings (T-Rank) admission is owned by
the sibling CBB workstream -- PR #2832 (archive admission record,
DESIGN only) and PR #2835 (hoopR substrate) -- including the morning-of
as-of rule for ratings. This module does NOT duplicate that admission.
It covers the distinct artifact this layer needs: Torvik's public
player advanced-stats CSV (getadvstats.php), the current-form player
surface (minutes share, offensive rating, usage, efficiency splits)
used as card context for CBB player props research.

Source: https://barttorvik.com/getadvstats.php?year=<season>&csv=1 --
publicly served CSV, no key, no account. Verified live 2026-10-27:
year=2027 pull returned 3,231 player rows, sha256
53f43e89a12708c4f2310ebce4a7dfbc843ce85693cb3328ec371700677ffccd.

HONEST SEASON NOTE: Torvik's `year` is the season-ending year (2027 =
2026-27). Pulled on 2026-10-27 -- before the 2026-27 season starts --
the endpoint serves the player pool with prior-season performance
rows. The fetcher stamps the requested season label and retrieval
time; consumers must read the row GP values rather than assume the
label means games have been played this season.

The CSV is HEADERLESS with a fixed published column order (the order
toRvik documents). Parsing is positional over the leading, stable
columns only, with a strict field-count check; any drift fails closed.

ILLINOIS COLLEGE EXCLUSION: CBB modeling scope excludes Illinois
college teams (owner standing rule). This fetcher returns the full
public table; exclusion is applied by consumers and recorded in the
factoring spec -- the fetcher itself never silently drops rows.

RESEARCH-ONLY: labeled context only.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from .common import Opener, fetch_bytes, receipt_of, to_float, to_int

TORVIK = "https://barttorvik.com/getadvstats.php"

# Positional columns (0-based) in Torvik's published getadvstats order.
# Only the leading block is consumed; the parser requires at least 30
# fields per row so a format change fails closed instead of misaligning.
MIN_FIELDS = 30
COLUMNS = {
    "player": 0,
    "team": 1,
    "conference": 2,
    "games": 3,
    "minutes_pct": 4,
    "offensive_rating": 5,
    "usage": 6,
    "efg_pct": 7,
    "ts_pct": 8,
    "orb_pct": 9,
    "drb_pct": 10,
    "ast_pct": 11,
    "to_pct": 12,
    "blk_pct": 22,
    "stl_pct": 23,
    "class_year": 25,
    "height": 26,
    "porpag": 28,  # points over replacement per adjusted game
    "adj_offensive_efficiency": 29,
}


def player_advanced_stats(*, season: int, opener: Opener | None = None) -> dict[str, Any]:
    """Fetch Torvik player advanced stats for one season label."""
    url = f"{TORVIK}?year={season}&csv=1"
    result = fetch_bytes(url, opener=opener)
    if result["status"] != "OK":
        return result
    try:
        text = result["body"].decode("utf-8-sig")
        raw_rows = [row for row in csv.reader(io.StringIO(text)) if row]
    except Exception:
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    if not raw_rows or any(len(row) < MIN_FIELDS for row in raw_rows):
        return {"status": "MISSING", "reason": "SCHEMA_DRIFT", "receipt": receipt_of(result)}
    players: list[dict[str, Any]] = []
    for row in raw_rows:
        entry: dict[str, Any] = {}
        for field, index in COLUMNS.items():
            raw = row[index]
            if field in ("player", "team", "conference", "class_year", "height"):
                entry[field] = raw
            elif field == "games":
                entry[field] = to_int(raw)
            else:
                entry[field] = to_float(raw)
        players.append(entry)
    return {
        "status": "OK",
        "source": "BartTorvik getadvstats player advanced stats (CSV)",
        "label": "RESEARCH_CONTEXT_ONLY",
        "season_label": season,
        "receipt": receipt_of(result),
        "players": players,
    }
