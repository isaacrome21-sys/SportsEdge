from __future__ import annotations

import csv
from hashlib import sha256
from io import StringIO
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError

PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
REQUIRED_COLUMNS = frozenset({
    "player_id", "player_name", "recent_team", "season", "week", "season_type",
    "attempts", "carries", "targets", "receptions", "receiving_air_yards",
    "target_share", "air_yards_share",
})


def _int(value: Any, field: str) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"{field} invalid") from exc


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError("NFLVERSE player stat numeric invalid") from exc


def fetch_nflverse_player_stats(*, season: int, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    """Fetch current nflverse weekly player stats with exact-byte provenance."""
    uri = PLAYER_STATS_URL.format(season=int(season))
    req = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
    try:
        with opener(req, timeout=25) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError("NFLVERSE player-stats fetch failed") from exc
    try:
        rows = [dict(row) for row in csv.DictReader(StringIO(raw.decode("utf-8-sig")))]
    except Exception as exc:
        raise NFLContextError("NFLVERSE player-stats CSV invalid") from exc
    if not rows:
        raise NFLContextError("NFLVERSE player-stats CSV empty")
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise NFLContextError("NFLVERSE player-stats schema unsupported:" + ",".join(sorted(missing)))
    return rows, uri, sha256(raw).hexdigest()


def build_prior_player_workload_inputs(
    *,
    rows: Iterable[Mapping[str, Any]],
    season: int,
    target_week: int,
    team_ids: Iterable[str],
    source_uri: str,
    source_sha256: str,
    max_games: int = 5,
) -> list[dict[str, Any]]:
    """Build strictly-prior-week usage histories for target teams and players.

    Same-week rows are excluded even if present. Weekly stats are objective box/PBP
    derivatives and provide carries, targets, air yards and shares; they do not
    claim routes or snap participation that this source does not contain. The
    player-id namespace is preserved explicitly and never fuzzily joined to PFR.
    """
    teams = {str(team or "").strip().upper() for team in team_ids if str(team or "").strip()}
    if not teams:
        return []
    grouped: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = {}
    for raw in rows:
        try:
            row_season = _int(raw.get("season"), "season")
            week = _int(raw.get("week"), "week")
        except NFLContextError:
            continue
        if row_season != int(season) or week >= int(target_week):
            continue
        if str(raw.get("season_type") or "REG").strip().upper() != "REG":
            continue
        team = str(raw.get("recent_team") or "").strip().upper()
        player_id = str(raw.get("player_id") or "").strip()
        if team not in teams or not player_id:
            continue
        grouped.setdefault((team, player_id), []).append((week, raw))

    out: list[dict[str, Any]] = []
    for (team, player_id), history in sorted(grouped.items()):
        history.sort(key=lambda item: item[0])
        selected = history[-int(max_games):]
        source_payload = {
            "identity_namespace": "GSIS",
            "gsis_player_id": player_id,
            "player_name": str(selected[-1][1].get("player_name") or "").strip() or None,
            "team_id": team,
            "sample_weeks": [week for week, _ in selected],
            "pass_attempts": [_number(row.get("attempts")) for _, row in selected],
            "carries": [_number(row.get("carries")) for _, row in selected],
            "targets": [_number(row.get("targets")) for _, row in selected],
            "receptions": [_number(row.get("receptions")) for _, row in selected],
            "receiving_air_yards": [_number(row.get("receiving_air_yards")) for _, row in selected],
            "target_share": [_number(row.get("target_share")) for _, row in selected],
            "air_yards_share": [_number(row.get("air_yards_share")) for _, row in selected],
            "routes": [],
            "snaps": [],
            "snap_share": [],
            "strictly_prior_week_only": True,
            "source_scope": "NFLVERSE_WEEKLY_PLAYER_STATS",
            "source_file_sha256": str(source_sha256),
        }
        out.append({
            "player_id": f"GSIS:{player_id}",
            "team_id": team,
            "source_uri": str(source_uri),
            "source_payload": source_payload,
            "injury_ramp_state": None,
            "short_week": None,
        })
    return out
