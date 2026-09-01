from __future__ import annotations

import csv
from hashlib import sha256
import io
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .context_autopull import NFLContextError

SNAP_COUNTS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "snap_counts/snap_counts_{season}.csv"
)
REQUIRED_FIELDS = frozenset({
    "game_id", "season", "game_type", "week", "player", "pfr_player_id",
    "position", "team", "opponent", "offense_snaps", "offense_pct",
    "defense_snaps", "defense_pct", "st_snaps", "st_pct",
})


def _int(value: Any, field: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"snap counts {field} invalid") from exc


def _optional_float(value: Any, field: str) -> float | None:
    if value in (None, "", "NA", "NaN", "nan"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLContextError(f"snap counts {field} invalid") from exc
    return out


def fetch_nflverse_snap_counts(
    *,
    season: int,
    opener: Callable = urlopen,
) -> tuple[list[dict[str, str]], str, str]:
    """Fetch one season of nflverse/PFR snap counts with exact-byte provenance."""
    resolved = int(season)
    uri = SNAP_COUNTS_URL.format(season=resolved)
    try:
        with opener(Request(uri, headers={"Accept": "text/csv"}), timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError("NFLVERSE_SNAP_COUNTS_FETCH_FAILED") from exc
    if not raw:
        raise NFLContextError("NFLVERSE_SNAP_COUNTS_EMPTY")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fields = set(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    except Exception as exc:
        raise NFLContextError("NFLVERSE_SNAP_COUNTS_CSV_INVALID") from exc
    missing = REQUIRED_FIELDS - fields
    if missing:
        raise NFLContextError("NFLVERSE_SNAP_COUNTS_SCHEMA_UNSUPPORTED:" + ",".join(sorted(missing)))
    return rows, uri, sha256(raw).hexdigest()


def build_prior_snap_workload_inputs(
    *,
    rows: Iterable[Mapping[str, Any]],
    season: int,
    target_week: int,
    team_ids: Iterable[str],
    source_uri: str,
    source_sha256: str,
    max_games: int = 5,
) -> list[dict[str, Any]]:
    """Build strictly-prior player workload histories for the target matchup.

    nflverse snap-count rows do not carry an authoritative kickoff timestamp, so
    same-week games are deliberately excluded even when they may already have
    occurred. This conservative rule prevents Thursday/Sunday ordering guesses
    from creating PIT leakage.
    """
    resolved_season = int(season)
    resolved_week = int(target_week)
    if resolved_week < 1:
        raise NFLContextError("snap workload target_week invalid")
    if isinstance(max_games, bool) or int(max_games) < 1:
        raise NFLContextError("snap workload max_games invalid")
    teams = {str(team).strip().upper() for team in team_ids if str(team).strip()}
    if not teams:
        raise NFLContextError("snap workload team_ids required")
    uri = str(source_uri or "").strip()
    if not uri.startswith("https://"):
        raise NFLContextError("snap workload source_uri must be https")
    digest = str(source_sha256 or "").strip().lower()
    if len(digest) != 64:
        raise NFLContextError("snap workload source_sha256 invalid")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise NFLContextError("snap workload source_sha256 invalid") from exc

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in rows:
        try:
            row_season = _int(raw.get("season"), "season")
            week = _int(raw.get("week"), "week")
        except NFLContextError:
            raise
        if row_season != resolved_season or week >= resolved_week:
            continue
        if str(raw.get("game_type") or "").strip().upper() != "REG":
            continue
        team = str(raw.get("team") or "").strip().upper()
        if team not in teams:
            continue
        player_id = str(raw.get("pfr_player_id") or "").strip()
        player_name = str(raw.get("player") or "").strip()
        if not player_id or not player_name:
            continue
        offense_snaps = _optional_float(raw.get("offense_snaps"), "offense_snaps")
        offense_pct = _optional_float(raw.get("offense_pct"), "offense_pct")
        if offense_pct is not None and offense_pct > 1.0:
            offense_pct /= 100.0
        if offense_pct is not None and not 0.0 <= offense_pct <= 1.0:
            raise NFLContextError("snap counts offense_pct outside [0,1]")
        grouped.setdefault((team, player_id), []).append({
            "week": week,
            "game_id": str(raw.get("game_id") or ""),
            "player_name": player_name,
            "position": str(raw.get("position") or "").strip().upper(),
            "offense_snaps": offense_snaps,
            "offense_pct": offense_pct,
        })

    output: list[dict[str, Any]] = []
    for (team, player_id), history in sorted(grouped.items()):
        history.sort(key=lambda row: (row["week"], row["game_id"]))
        window = history[-int(max_games):]
        snaps = [row["offense_snaps"] for row in window if row["offense_snaps"] is not None]
        shares = [row["offense_pct"] for row in window if row["offense_pct"] is not None]
        if not snaps and not shares:
            continue
        output.append({
            "player_id": f"PFR:{player_id}",
            "team_id": team,
            "source_uri": uri,
            "source_payload": {
                "identity_namespace": "PFR",
                "pfr_player_id": player_id,
                "player_name": window[-1]["player_name"],
                "position": window[-1]["position"],
                "sample_weeks": [row["week"] for row in window],
                "sample_game_ids": [row["game_id"] for row in window],
                "snaps": snaps,
                "snap_share": shares,
                "routes": [],
                "targets": [],
                "carries": [],
                "strictly_prior_week_only": True,
                "source_file_sha256": digest,
            },
            "injury_ramp_state": None,
            "short_week": None,
        })
    return output
