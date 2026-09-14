from __future__ import annotations

import csv
from hashlib import sha256
import io
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from sportsedge.sports.nfl.context_autopull import NFLContextError

NFLVERSE_PLAYER_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)

_ID_FIELDS = ("player_id", "player_display_name", "player_name", "position", "team", "opponent_team")
_NUMERIC_FIELDS = (
    "season", "week", "attempts", "passing_yards", "passing_tds", "interceptions",
    "carries", "rushing_yards", "rushing_tds", "targets", "receptions",
    "receiving_yards", "receiving_tds", "fumbles_lost",
)
_REQUIRED = frozenset({
    "player_id", "player_display_name", "position", "season", "week", "season_type",
    "team", "attempts", "passing_yards", "passing_tds", "interceptions", "carries",
    "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards",
    "receiving_tds",
})


def _num(value: Any) -> float:
    if value in (None, "", "NA", "NaN", "nan"):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"NFLVERSE_PLAYER_STATS_NUMERIC_INVALID:{value}") from exc


def fetch_nflverse_player_stats(
    *,
    season: int,
    opener: Callable = urlopen,
) -> tuple[list[dict[str, str]], str, str]:
    """Fetch nflverse weekly player stats with exact-byte provenance.

    The URL matches nflreadr's public `load_player_stats(..., summary_level='week')`
    release contract. Missing current-season assets fail closed; callers may then use
    a separately declared fallback source rather than fabricating empty history.
    """
    resolved = int(season)
    uri = NFLVERSE_PLAYER_STATS_URL.format(season=resolved)
    try:
        with opener(Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"}), timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError(f"NFLVERSE_PLAYER_STATS_FETCH_FAILED:{resolved}") from exc
    if not raw:
        raise NFLContextError(f"NFLVERSE_PLAYER_STATS_EMPTY:{resolved}")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        fields = set(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    except Exception as exc:
        raise NFLContextError("NFLVERSE_PLAYER_STATS_CSV_INVALID") from exc
    missing = _REQUIRED - fields
    if missing:
        raise NFLContextError("NFLVERSE_PLAYER_STATS_SCHEMA_UNSUPPORTED:" + ",".join(sorted(missing)))
    if not rows:
        raise NFLContextError(f"NFLVERSE_PLAYER_STATS_EMPTY:{resolved}")
    return rows, uri, sha256(raw).hexdigest()


def build_prior_player_stat_history(
    *,
    current_rows: Iterable[Mapping[str, Any]],
    prior_rows: Iterable[Mapping[str, Any]] = (),
    season: int,
    target_week: int,
    team_ids: Iterable[str],
    current_source_uri: str,
    current_source_sha256: str,
    prior_source_uri: str | None = None,
    prior_source_sha256: str | None = None,
    max_games: int = 10,
) -> dict[str, Any]:
    """Build a strictly-prior, replayable player-stat history for one NFL matchup.

    Current-season rows use only `week < target_week`. Prior-season rows are allowed
    only from `season - 1` regular season. Same-week games are excluded deliberately
    because weekly player-stat files do not prove intra-week pregame ordering.
    """
    resolved_season = int(season)
    resolved_week = int(target_week)
    if resolved_week < 1:
        raise NFLContextError("NFL_DFS_TARGET_WEEK_INVALID")
    if isinstance(max_games, bool) or int(max_games) < 1:
        raise NFLContextError("NFL_DFS_MAX_GAMES_INVALID")
    teams = {str(team or "").strip().upper() for team in team_ids}
    teams.discard("")
    if not teams:
        raise NFLContextError("NFL_DFS_TEAM_IDS_REQUIRED")
    if not str(current_source_uri).startswith("https://") or len(str(current_source_sha256)) != 64:
        raise NFLContextError("NFL_DFS_CURRENT_STATS_PROVENANCE_INVALID")
    if prior_rows and (
        not str(prior_source_uri or "").startswith("https://")
        or len(str(prior_source_sha256 or "")) != 64
    ):
        raise NFLContextError("NFL_DFS_PRIOR_STATS_PROVENANCE_INVALID")

    accepted: list[dict[str, Any]] = []
    for source_label, rows, expected_season, source_uri, digest in (
        ("CURRENT", current_rows, resolved_season, current_source_uri, current_source_sha256),
        ("PRIOR", prior_rows, resolved_season - 1, prior_source_uri, prior_source_sha256),
    ):
        for raw in rows:
            row_season = int(_num(raw.get("season")))
            week = int(_num(raw.get("week")))
            if row_season != expected_season:
                continue
            if str(raw.get("season_type") or "").strip().upper() not in {"REG", "REGULAR"}:
                continue
            if source_label == "CURRENT" and week >= resolved_week:
                continue
            team = str(raw.get("team") or "").strip().upper()
            if team not in teams:
                continue
            player_id = str(raw.get("player_id") or "").strip()
            display = str(raw.get("player_display_name") or raw.get("player_name") or "").strip()
            if not player_id or not display:
                continue
            row: dict[str, Any] = {
                "player_id": player_id,
                "player_display_name": display,
                "player_name": str(raw.get("player_name") or "").strip(),
                "position": str(raw.get("position") or "").strip().upper(),
                "team": team,
                "opponent_team": str(raw.get("opponent_team") or "").strip().upper(),
                "season": row_season,
                "week": week,
                "source_label": source_label,
                "source_uri": str(source_uri or ""),
                "source_sha256": str(digest or ""),
            }
            for field in _NUMERIC_FIELDS:
                if field in {"season", "week"}:
                    continue
                row[field] = _num(raw.get(field))
            accepted.append(row)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in accepted:
        grouped.setdefault((row["team"], row["player_id"]), []).append(row)
    players: list[dict[str, Any]] = []
    for (team, player_id), rows in sorted(grouped.items()):
        rows.sort(key=lambda r: (r["season"], r["week"]))
        window = rows[-int(max_games):]
        players.append({
            "player_id": player_id,
            "team": team,
            "player_display_name": window[-1]["player_display_name"],
            "position": window[-1]["position"],
            "games": window,
        })

    return {
        "schema_version": 1,
        "sport": "NFL",
        "season": resolved_season,
        "target_week": resolved_week,
        "teams": sorted(teams),
        "strictly_prior_week_only": True,
        "max_games": int(max_games),
        "current_source_uri": current_source_uri,
        "current_source_sha256": current_source_sha256,
        "prior_source_uri": prior_source_uri,
        "prior_source_sha256": prior_source_sha256,
        "player_count": len(players),
        "players": players,
    }
