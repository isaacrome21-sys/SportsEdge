from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .scoring import dk_fppg_baseline, projection_from_samples, projection_from_stats
from .types import DKPlayer, Projection


def _finite_number(value: Any, field: str, player_id: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"DFS_PROJECTION_NUMBER_INVALID:{player_id}:{field}")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"DFS_PROJECTION_NUMBER_INVALID:{player_id}:{field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"DFS_PROJECTION_NUMBER_INVALID:{player_id}:{field}")
    return number


def _ownership(value: Any, player_id: str) -> float | None:
    if value is None:
        return None
    number = _finite_number(value, "ownership", player_id)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"DFS_PROJECTION_OWNERSHIP_OUT_OF_RANGE:{player_id}")
    return number


def _validate_projection(proj: Projection) -> Projection:
    """Reject malformed scores even when generated from samples or stat rows."""
    pid = proj.player_id
    mean = _finite_number(proj.mean, "mean", pid)
    floor = _finite_number(proj.floor, "floor", pid)
    ceiling = _finite_number(proj.ceiling, "ceiling", pid)
    if mean < 0 or not 0 <= floor <= mean <= ceiling:
        raise ValueError(f"DFS_PROJECTION_QUANTILES_INVALID:{pid}")
    if proj.stddev is not None and _finite_number(proj.stddev, "stddev", pid) < 0:
        raise ValueError(f"DFS_PROJECTION_STDDEV_NEGATIVE:{pid}")
    _ownership(proj.ownership, pid)
    for name, value in proj.components.items():
        _finite_number(value, f"component:{name}", pid)
    return proj


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
    pool = list(players)
    by_id = {p.player_id: p for p in pool}
    by_name_team: dict[tuple[str, str], DKPlayer | None] = {}
    for player in pool:
        key = (player.name.casefold(), player.team)
        by_name_team[key] = player if key not in by_name_team else None
    out: dict[str, Projection] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("player_id") or row.get("playerDkId") or "")
        p = by_id.get(pid)
        if p is None:
            key = (str(row.get("name") or "").casefold(), str(row.get("team") or "").upper())
            if key in by_name_team and by_name_team[key] is None:
                raise ValueError(f"DFS_PROJECTION_PLAYER_AMBIGUOUS:{key[0]}:{key[1]}")
            p = by_name_team.get(key)
        if p is None:
            continue
        if p.player_id in out:
            raise ValueError(f"DFS_PROJECTION_DUPLICATE_PLAYER:{p.player_id}")
        if isinstance(row.get("samples"), list):
            proj = projection_from_samples(
                p,
                sport,
                row["samples"],
                source=str(row.get("source") or "SPORTSEDGE_DISTRIBUTION"),
                ownership=_ownership(row.get("ownership"), p.player_id),
            )
            out[p.player_id] = _validate_projection(Projection(
                **{**proj.__dict__, "updated_at": _dt(row.get("updated_at")) or snapshot_updated_at}
            ))
            continue
        if isinstance(row.get("stats"), dict):
            proj = projection_from_stats(p, sport, row["stats"], source=str(row.get("source") or "SPORTSEDGE_STATS"))
            out[p.player_id] = _validate_projection(Projection(
                **{**proj.__dict__, "updated_at": _dt(row.get("updated_at")) or snapshot_updated_at}
            ))
            continue
        mean = _finite_number(row.get("mean") if row.get("mean") is not None
                              else row.get("projection", 0.0), "mean", p.player_id)
        if mean < 0:
            raise ValueError(f"DFS_PROJECTION_MEAN_NEGATIVE:{p.player_id}")
        if mean <= 0:
            continue
        raw_std = row.get("stddev")
        std_value = (_finite_number(raw_std, "stddev", p.player_id)
                     if raw_std is not None else 0.0)
        std = std_value or None
        if std is not None and std < 0:
            raise ValueError(f"DFS_PROJECTION_STDDEV_NEGATIVE:{p.player_id}")
        ceiling = (_finite_number(row["ceiling"], "ceiling", p.player_id)
                   if row.get("ceiling") is not None else mean + (1.65 * std if std else max(4.0, mean * 0.45)))
        floor = (_finite_number(row["floor"], "floor", p.player_id)
                 if row.get("floor") is not None else max(0.0, mean - (1.15 * std if std else max(3.0, mean * 0.35))))
        if ceiling < mean or not 0.0 <= floor <= mean:
            raise ValueError(f"DFS_PROJECTION_QUANTILES_INVALID:{p.player_id}")
        raw_components = row.get("components")
        components = {} if raw_components is None else raw_components
        if not isinstance(components, dict):
            raise ValueError(f"DFS_PROJECTION_COMPONENTS_INVALID:{p.player_id}")
        out[p.player_id] = _validate_projection(Projection(
            player_id=p.player_id,
            mean=mean,
            ceiling=max(mean, ceiling),
            floor=max(0.0, min(mean, floor)),
            stddev=std,
            ownership=_ownership(row.get("ownership"), p.player_id),
            source=str(row.get("source") or payload.get("source") if isinstance(payload, dict) else "SNAPSHOT"),
            updated_at=_dt(row.get("updated_at")) or snapshot_updated_at,
            components={str(k): _finite_number(v, f"component:{k}", p.player_id)
                        for k, v in components.items()},
        ))
    return out


def ensure_projection_coverage(
    players: Iterable[DKPlayer],
    projections: dict[str, Projection],
    *,
    allow_dk_fppg_baseline: bool,
) -> dict[str, Projection]:
    out: dict[str, Projection] = {}
    for pid, proj in projections.items():
        if pid != proj.player_id:
            raise ValueError(f"DFS_PROJECTION_PLAYER_ID_MISMATCH:{pid}:{proj.player_id}")
        out[pid] = _validate_projection(proj)
    active = [p for p in players if not p.is_disabled]
    for p in active:
        if p.player_id in out:
            continue
        if allow_dk_fppg_baseline and p.dk_fppg is not None:
            if isinstance(p.dk_fppg, bool) or _finite_number(
                p.dk_fppg, "dk_fppg", p.player_id
            ) < 0:
                raise ValueError(f"DFS_DK_FPPG_INVALID:{p.player_id}")
            out[p.player_id] = _validate_projection(dk_fppg_baseline(p))
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
