from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from .scoring import dk_fppg_baseline, projection_from_stats
from .types import DKPlayer, Projection


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def load_projection_snapshot(path: str | Path, players: Iterable[DKPlayer], sport: str) -> dict[str, Projection]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    snapshot_updated_at = _dt(payload.get("updated_at")) if isinstance(payload, dict) else None
    rows = payload.get("players") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("DFS_PROJECTION_SNAPSHOT_SHAPE_INVALID")
    by_id = {p.player_id: p for p in players}
    by_name_team = {(p.name.casefold(), p.team): p for p in players}
    out: dict[str, Projection] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("player_id") or row.get("playerDkId") or "")
        p = by_id.get(pid)
        if p is None:
            key = (str(row.get("name") or "").casefold(), str(row.get("team") or "").upper())
            p = by_name_team.get(key)
        if p is None:
            continue
        if isinstance(row.get("stats"), dict):
            proj = projection_from_stats(p, sport, row["stats"], source=str(row.get("source") or "SPORTSEDGE_STATS"))
            out[p.player_id] = Projection(
                **{**proj.__dict__, "updated_at": _dt(row.get("updated_at")) or snapshot_updated_at}
            )
            continue
        mean = float(row.get("mean") or row.get("projection") or 0.0)
        if mean <= 0:
            continue
        std = float(row.get("stddev") or 0.0) or None
        ceiling = float(row.get("ceiling") or 0.0) or mean + (1.65 * std if std else max(4.0, mean * 0.45))
        floor = float(row.get("floor") or 0.0) or max(0.0, mean - (1.15 * std if std else max(3.0, mean * 0.35)))
        own = row.get("ownership")
        out[p.player_id] = Projection(
            player_id=p.player_id,
            mean=mean,
            ceiling=max(mean, ceiling),
            floor=max(0.0, min(mean, floor)),
            stddev=std,
            ownership=float(own) if own is not None else None,
            source=str(row.get("source") or payload.get("source") if isinstance(payload, dict) else "SNAPSHOT"),
            updated_at=_dt(row.get("updated_at")) or snapshot_updated_at,
            components={str(k): float(v) for k, v in (row.get("components") or {}).items() if isinstance(v, (int, float))},
        )
    return out


def ensure_projection_coverage(
    players: Iterable[DKPlayer],
    projections: dict[str, Projection],
    *,
    allow_dk_fppg_baseline: bool,
) -> dict[str, Projection]:
    out = dict(projections)
    active = [p for p in players if not p.is_disabled]
    for p in active:
        if p.player_id in out:
            continue
        if allow_dk_fppg_baseline and p.dk_fppg is not None:
            out[p.player_id] = dk_fppg_baseline(p)
    usable = sum(1 for p in active if p.player_id in out)
    coverage = usable / max(1, len(active))
    if coverage < 0.90:
        raise ValueError(f"DFS_PROJECTION_COVERAGE_TOO_LOW:{coverage:.3f}")
    return out


def validate_projection_freshness(
    players: Iterable[DKPlayer],
    projections: dict[str, Projection],
    *,
    slate_start: datetime,
    max_age: timedelta,
    allow_untimestamped_sources: frozenset[str] = frozenset({"DK_FPPG_BASELINE"}),
) -> dict[str, float | int | str]:
    """Fail closed on future-dated or stale DFS projection evidence.

    Every non-baseline projection used by the optimizer must prove it existed before
    the slate lock and must be recent enough for the requested slate.
    """
    if slate_start.tzinfo is None:
        raise ValueError("DFS_SLATE_START_MUST_BE_TIMEZONE_AWARE")
    cutoff = slate_start.astimezone(timezone.utc)
    active_ids = {p.player_id for p in players if not p.is_disabled}
    checked = 0
    ages: list[float] = []
    for pid, proj in projections.items():
        if pid not in active_ids:
            continue
        if proj.updated_at is None:
            if proj.source in allow_untimestamped_sources:
                continue
            raise ValueError(f"DFS_PROJECTION_TIMESTAMP_MISSING:{pid}:{proj.source}")
        ts = proj.updated_at.astimezone(timezone.utc)
        if ts > cutoff:
            raise ValueError(f"DFS_PROJECTION_AFTER_LOCK:{pid}:{ts.isoformat()}")
        age = cutoff - ts
        if age > max_age:
            raise ValueError(f"DFS_PROJECTION_STALE:{pid}:{age.total_seconds()/3600:.2f}H")
        checked += 1
        ages.append(age.total_seconds() / 3600.0)
    return {
        "timestamped_projection_count": checked,
        "max_projection_age_hours": round(max(ages), 3) if ages else 0.0,
        "freshness_limit_hours": round(max_age.total_seconds() / 3600.0, 3),
        "freshness_state": "PASS",
    }
