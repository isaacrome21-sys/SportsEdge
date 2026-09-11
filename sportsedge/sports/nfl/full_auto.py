from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .auto_slate import build_nfl_auto_context_slate
from .context_autopull import ContextObservation, NFLContextError
from .player_stats_workload_source import fetch_nflverse_player_stats
from .snap_workload_source import fetch_nflverse_snap_counts

DEPTH_CHART_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv"


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        try:
            out = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise NFLContextError("as_of invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NFLContextError("as_of timezone required")
    return out.astimezone(timezone.utc)


def fetch_nflverse_depth_charts(*, season: int, opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    """Fetch the current nflverse weekly depth-chart CSV with immutable provenance."""
    uri = DEPTH_CHART_URL.format(season=int(season))
    req = Request(uri, headers={"User-Agent": "SportsEdge/1.0", "Accept": "text/csv"})
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise NFLContextError("NFLVERSE depth-chart fetch failed") from exc
    try:
        text = raw.decode("utf-8-sig")
        rows = [dict(row) for row in csv.DictReader(StringIO(text))]
    except Exception as exc:
        raise NFLContextError("NFLVERSE depth-chart CSV invalid") from exc
    if not rows:
        raise NFLContextError("NFLVERSE depth-chart CSV empty")
    required_any = ({"team", "dt"}, {"club_code", "week"})
    columns = set(rows[0])
    if not any(required <= columns for required in required_any):
        raise NFLContextError("NFLVERSE depth-chart schema unsupported")
    return rows, uri, sha256(raw).hexdigest()


def _source_result(future, label: str):
    try:
        rows, uri, digest = future.result()
        return rows, uri, digest, "AVAILABLE"
    except NFLContextError as exc:
        return None, None, None, f"MISSING:{exc}"
    except Exception as exc:
        return None, None, None, f"SOURCE_FAILED:{label}:{type(exc).__name__}"


def build_nfl_full_auto_slate(
    *,
    as_of: Any,
    season: int | None = None,
    mode: str = "AUTO",
    min_lead_minutes: int = 0,
    horizon_minutes: int = 7 * 24 * 60,
    game_types: Iterable[str] = ("REG",),
    manual_observations_by_game: Mapping[str, Iterable[ContextObservation]] | None = None,
    opener: Callable = urlopen,
) -> dict[str, Any]:
    """Canonical zero-game-list NFL AUTO/HYBRID context entry point.

    Independent depth-chart, snap-count and weekly player-usage sources are
    acquired concurrently. Any one can fail without fabricating values or blocking
    unrelated context. Both workload sources exclude the target week because they
    do not carry authoritative event timestamps suitable for safe intra-week PIT.
    """
    pit = _utc(as_of)
    resolved_season = int(season if season is not None else pit.year)

    with ThreadPoolExecutor(max_workers=3) as pool:
        depth_future = pool.submit(fetch_nflverse_depth_charts, season=resolved_season, opener=opener)
        snap_future = pool.submit(fetch_nflverse_snap_counts, season=resolved_season, opener=opener)
        stats_future = pool.submit(fetch_nflverse_player_stats, season=resolved_season, opener=opener)
        depth_rows, depth_uri, depth_sha, depth_status = _source_result(depth_future, "DEPTH_CHART")
        snap_rows, snap_uri, snap_sha, snap_status = _source_result(snap_future, "SNAP_COUNTS")
        stats_rows, stats_uri, stats_sha, stats_status = _source_result(stats_future, "PLAYER_STATS")

    slate = build_nfl_auto_context_slate(
        as_of=pit,
        mode=mode,
        min_lead_minutes=min_lead_minutes,
        horizon_minutes=horizon_minutes,
        game_types=game_types,
        manual_observations_by_game=manual_observations_by_game,
        depth_chart_rows=depth_rows,
        depth_chart_source_uri=depth_uri,
        depth_chart_source_sha256=depth_sha,
        snap_count_rows=snap_rows,
        snap_count_source_uri=snap_uri,
        snap_count_source_sha256=snap_sha,
        player_stat_rows=stats_rows,
        player_stat_source_uri=stats_uri,
        player_stat_source_sha256=stats_sha,
        opener=opener,
    )
    slate["automation"] = {
        "entry_point": "build_nfl_full_auto_slate",
        "operator_game_list_required": False,
        "depth_chart_status": depth_status,
        "depth_chart_source_uri": depth_uri,
        "snap_count_status": snap_status,
        "snap_count_source_uri": snap_uri,
        "snap_workload_pit_policy": "STRICTLY_PRIOR_WEEK_ONLY",
        "player_stats_status": stats_status,
        "player_stats_source_uri": stats_uri,
        "player_stats_pit_policy": "STRICTLY_PRIOR_WEEK_ONLY",
        "player_stats_identity_namespace": "GSIS",
        "snap_counts_identity_namespace": "PFR",
        "cross_namespace_fuzzy_join": False,
        "market_context_ingested": False,
        "social_context_ingested": False,
    }
    return slate
