"""NFL Next Gen Stats acquisition via nflverse's documented data releases.

Source: https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{stat_type}.csv.gz

nflverse republishes NFL Next Gen Stats (passing / rushing / receiving) as
versioned, documented release assets. The loader contract mirrors nflreadr's
``load_nextgen_stats`` (data dictionary at nflreadr.nflverse.com); rows are
week-level per player, with ``week == 0`` carrying the regular-season summary.

Verified 2026-10-11: seasons 2016--2026 present, current season refreshed
nightly in-season (2026 weeks 0--5 observed). Tracking columns include
``avg_time_to_throw``, ``avg_completed_air_yards``, ``avg_intended_air_yards``,
``aggressiveness``, ``expected_completion_percentage``,
``completion_percentage_above_expectation`` (passing); rushing/receiving carry
their own documented metric sets.

Acquisition layer only. ``rolling_player_metrics`` enforces strict
no-lookahead: a target week sees only strictly earlier weeks of the same
season (``week == 0`` summaries are excluded from rolling windows).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.request import Request, urlopen
import csv
import gzip
import io

SOURCE = "NFLVERSE_NGS"
SCHEMA_VERSION = "nflverse_ngs_v1"
RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats"
STAT_TYPES = ("passing", "rushing", "receiving")
REQUIRED_COLUMNS = frozenset({"season", "season_type", "week", "player_display_name"})
PLAYER_KEY_COLUMNS = ("player_gsis_id", "player_display_name")
SUMMARY_WEEK = "0"


class NGSFetchError(RuntimeError):
    pass


def _fail(code: str) -> NGSFetchError:
    return NGSFetchError(f"NGS_{code}")


def asset_url(stat_type: str) -> str:
    st = str(stat_type or "").strip().lower()
    if st not in STAT_TYPES:
        raise _fail(f"STAT_TYPE_INVALID:{stat_type}")
    return f"{RELEASE_BASE}/ngs_{st}.csv.gz"


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        out = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def fetch_ngs(stat_type: str, *, opener: Callable = urlopen, timeout: int = 120) -> list[dict[str, str]]:
    """Download and parse one NGS stat-type asset. Fail-closed on any anomaly."""
    url = asset_url(stat_type)
    req = Request(url, headers={
        "Accept": "application/gzip",
        "User-Agent": "SportsEdge-NGS/1.0",
    })
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read()
    except Exception as exc:
        raise _fail(f"FETCH_FAILED:{type(exc).__name__}") from exc
    if not raw:
        raise _fail("EMPTY_RESPONSE")
    try:
        text = gzip.decompress(raw).decode("utf-8")
    except Exception as exc:
        raise _fail("GZIP_DECODE_FAILED") from exc
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:
        raise _fail("CSV_PARSE_FAILED") from exc
    if not rows:
        raise _fail("NO_ROWS")
    missing = REQUIRED_COLUMNS - set(rows[0].keys())
    if missing:
        raise _fail(f"SCHEMA_MISSING:{sorted(missing)}")
    return rows


def player_key(row: Mapping[str, Any]) -> str:
    for col in PLAYER_KEY_COLUMNS:
        val = str(row.get(col) or "").strip()
        if val:
            return val
    raise _fail("PLAYER_KEY_MISSING")


@dataclass(frozen=True)
class PlayerRollingMetrics:
    stat_type: str
    season: int
    target_week: int
    player_key: str
    player_display_name: str
    window_weeks: tuple[int, ...]
    n_weeks: int
    metrics: tuple[tuple[str, float], ...]


def _numeric_columns(rows: Iterable[Mapping[str, Any]], exclude: frozenset[str]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for key, value in row.items():
            if key in exclude or key in cols:
                continue
            if _to_float(value) is not None:
                cols.append(key)
        break
    return cols


def rolling_player_metrics(
    rows: Iterable[Mapping[str, Any]],
    *,
    stat_type: str,
    season: int,
    week: int,
    window: int = 4,
    min_weeks: int = 1,
) -> list[PlayerRollingMetrics]:
    """Per-player rolling means over strictly-prior weeks (no lookahead).

    Only rows with ``season == season`` and ``1 <= week < target`` are used;
    ``week == 0`` (season summary) never enters a rolling window. Raises
    ``NGS_NO_PRIOR_WEEKS`` when no player has enough history.
    """
    st = str(stat_type or "").strip().lower()
    if st not in STAT_TYPES:
        raise _fail(f"STAT_TYPE_INVALID:{stat_type}")
    if window < 1:
        raise _fail("WINDOW_INVALID")
    season_rows = [
        r for r in rows
        if _to_int(r.get("season")) == season
        and _to_int(r.get("week")) is not None
        and 1 <= _to_int(r.get("week")) < week
    ]
    if not season_rows:
        raise _fail("NO_PRIOR_WEEKS")
    exclude = frozenset({"season", "week", "player_gsis_id", "player_display_name",
                         "player_first_name", "player_last_name", "player_short_name",
                         "player_position", "team_abbr", "season_type", "player_jersey_number"})
    metric_cols = _numeric_columns(season_rows, exclude)
    by_player: dict[str, list[Mapping[str, Any]]] = {}
    for row in season_rows:
        by_player.setdefault(player_key(row), []).append(row)
    out: list[PlayerRollingMetrics] = []
    for key in sorted(by_player):
        prows = sorted(by_player[key], key=lambda r: _to_int(r.get("week")))
        recent = prows[-window:]
        if len(recent) < min_weeks:
            continue
        metrics: list[tuple[str, float]] = []
        for col in metric_cols:
            vals = [_to_float(r.get(col)) for r in recent]
            vals = [v for v in vals if v is not None]
            if vals:
                metrics.append((col, round(sum(vals) / len(vals), 6)))
        out.append(PlayerRollingMetrics(
            stat_type=st,
            season=season,
            target_week=week,
            player_key=key,
            player_display_name=str(prows[-1].get("player_display_name") or ""),
            window_weeks=tuple(_to_int(r.get("week")) for r in recent),
            n_weeks=len(recent),
            metrics=tuple(metrics),
        ))
    if not out:
        raise _fail("NO_PRIOR_WEEKS")
    return out
