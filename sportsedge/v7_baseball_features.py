from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from .runtime import parse_timestamp
from .source_lineage import canonical_json_sha256

V7_FEATURE_CONTRACT_VERSION = "mlb_v7_baseball_features_v1"

BANNED_MARKET_KEYS = frozenset({
    "sportsbook", "bookmaker", "book_key", "american_odds", "american_price",
    "decimal_odds", "decimal_price", "implied_probability", "devig_probability",
    "market_probability", "market_consensus", "sharp_probability", "closing_line",
    "market_edge", "market_ev", "offered_price", "sportsbook_probability",
})


class V7FeatureError(ValueError):
    pass


@dataclass(frozen=True)
class StarterWorkloadFeatures:
    days_rest: float
    pitches_7d: float
    pitches_14d: float
    starts_30d: float
    avg_pitches_5starts: float


@dataclass(frozen=True)
class BullpenWorkloadFeatures:
    relief_pitches_1d: float
    relief_pitches_3d: float
    relief_pitches_7d: float
    relievers_used_1d: float
    relievers_back_to_back: float


@dataclass(frozen=True)
class RollingStatcastFeatures:
    pa_7d: float
    pa_14d: float
    pa_30d: float
    pa_75d: float
    xwoba_14d: float
    xwoba_30d: float
    hard_hit_30d: float
    barrel_30d: float
    whiff_30d: float


@dataclass(frozen=True)
class PlatoonFeatures:
    batter_hand: str
    pitcher_hand: str
    same_side: float
    batter_xwoba_vs_hand: float
    pitcher_xwoba_allowed_vs_hand: float


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise V7FeatureError(f"invalid {field}") from exc
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise V7FeatureError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _float(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise V7FeatureError(f"{field} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V7FeatureError(f"{field} must be numeric") from exc
    if not isfinite(out):
        raise V7FeatureError(f"{field} must be finite")
    if minimum is not None and out < minimum:
        raise V7FeatureError(f"{field} below minimum")
    if maximum is not None and out > maximum:
        raise V7FeatureError(f"{field} above maximum")
    return out


def assert_no_market_contamination(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in BANNED_MARKET_KEYS:
                raise V7FeatureError(f"sportsbook/market field prohibited in V7 feature contract: {path}.{key}")
            assert_no_market_contamination(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, child in enumerate(value):
            assert_no_market_contamination(child, path=f"{path}[{i}]")


def _eligible_rows(rows: Iterable[Mapping[str, Any]], *, as_of: datetime, time_key: str = "event_time") -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise V7FeatureError("feature history row must be an object")
        event_time = _utc(row.get(time_key), time_key)
        if event_time >= as_of:
            continue
        out.append(row)
    out.sort(key=lambda r: _utc(r.get(time_key), time_key))
    return out


def _window(rows: Sequence[Mapping[str, Any]], *, as_of: datetime, days: int, time_key: str = "event_time") -> list[Mapping[str, Any]]:
    cutoff = as_of - timedelta(days=days)
    return [r for r in rows if cutoff <= _utc(r.get(time_key), time_key) < as_of]


def starter_workload(rows: Iterable[Mapping[str, Any]], *, as_of: Any) -> StarterWorkloadFeatures:
    asof = _utc(as_of, "as_of")
    history = _eligible_rows(rows, as_of=asof)
    starts = [r for r in history if bool(r.get("is_start"))]
    if not starts:
        raise V7FeatureError("starter history missing")
    last = starts[-1]
    last_time = _utc(last["event_time"], "event_time")
    days_rest = max(0.0, (asof - last_time).total_seconds() / 86400.0)
    def pitches_in(days: int) -> float:
        return sum(_float(r.get("pitches", 0), "pitches", minimum=0) for r in _window(history, as_of=asof, days=days))
    recent_starts = starts[-5:]
    return StarterWorkloadFeatures(
        days_rest=days_rest,
        pitches_7d=pitches_in(7),
        pitches_14d=pitches_in(14),
        starts_30d=float(len(_window(starts, as_of=asof, days=30))),
        avg_pitches_5starts=mean(_float(r.get("pitches", 0), "pitches", minimum=0) for r in recent_starts),
    )


def bullpen_workload(rows: Iterable[Mapping[str, Any]], *, as_of: Any) -> BullpenWorkloadFeatures:
    asof = _utc(as_of, "as_of")
    history = [r for r in _eligible_rows(rows, as_of=asof) if not bool(r.get("is_start"))]
    def pitches(days: int) -> float:
        return sum(_float(r.get("pitches", 0), "pitches", minimum=0) for r in _window(history, as_of=asof, days=days))
    one_day = _window(history, as_of=asof, days=1)
    three_day = _window(history, as_of=asof, days=3)
    by_pitcher: dict[str, set[str]] = {}
    for r in three_day:
        pid = str(r.get("pitcher_id", "")).strip()
        if not pid:
            raise V7FeatureError("bullpen row missing pitcher_id")
        day = _utc(r["event_time"], "event_time").date().isoformat()
        by_pitcher.setdefault(pid, set()).add(day)
    back_to_back = sum(1 for days in by_pitcher.values() if len(days) >= 2)
    return BullpenWorkloadFeatures(
        relief_pitches_1d=pitches(1),
        relief_pitches_3d=pitches(3),
        relief_pitches_7d=pitches(7),
        relievers_used_1d=float(len({str(r.get("pitcher_id")) for r in one_day})),
        relievers_back_to_back=float(back_to_back),
    )


def rolling_statcast(rows: Iterable[Mapping[str, Any]], *, as_of: Any) -> RollingStatcastFeatures:
    asof = _utc(as_of, "as_of")
    history = _eligible_rows(rows, as_of=asof)
    def w(days: int) -> list[Mapping[str, Any]]:
        return _window(history, as_of=asof, days=days)
    def avg(rows_: Sequence[Mapping[str, Any]], key: str, default: float = 0.0) -> float:
        vals = [_float(r[key], key) for r in rows_ if r.get(key) is not None]
        return mean(vals) if vals else default
    def rate(rows_: Sequence[Mapping[str, Any]], key: str) -> float:
        vals = [_float(r.get(key, 0), key, minimum=0, maximum=1) for r in rows_]
        return mean(vals) if vals else 0.0
    w7, w14, w30, w75 = w(7), w(14), w(30), w(75)
    return RollingStatcastFeatures(
        pa_7d=float(len(w7)), pa_14d=float(len(w14)), pa_30d=float(len(w30)), pa_75d=float(len(w75)),
        xwoba_14d=avg(w14, "xwoba"), xwoba_30d=avg(w30, "xwoba"),
        hard_hit_30d=rate(w30, "hard_hit"), barrel_30d=rate(w30, "barrel"), whiff_30d=rate(w30, "whiff"),
    )


def platoon_features(*, batter_hand: Any, pitcher_hand: Any, batter_xwoba_vs_hand: Any, pitcher_xwoba_allowed_vs_hand: Any) -> PlatoonFeatures:
    bh = str(batter_hand or "").strip().upper()
    ph = str(pitcher_hand or "").strip().upper()
    if bh not in {"L", "R", "S"} or ph not in {"L", "R"}:
        raise V7FeatureError("invalid batter/pitcher handedness")
    same = 0.0 if bh == "S" else float(bh == ph)
    return PlatoonFeatures(
        batter_hand=bh,
        pitcher_hand=ph,
        same_side=same,
        batter_xwoba_vs_hand=_float(batter_xwoba_vs_hand, "batter_xwoba_vs_hand", minimum=0, maximum=1),
        pitcher_xwoba_allowed_vs_hand=_float(pitcher_xwoba_allowed_vs_hand, "pitcher_xwoba_allowed_vs_hand", minimum=0, maximum=1),
    )


def build_v7_baseball_features(*, as_of: Any, starter_rows: Iterable[Mapping[str, Any]], bullpen_rows: Iterable[Mapping[str, Any]], statcast_rows: Iterable[Mapping[str, Any]], platoon: Mapping[str, Any]) -> dict[str, Any]:
    asof = _utc(as_of, "as_of")
    payload = {
        "feature_contract_version": V7_FEATURE_CONTRACT_VERSION,
        "feature_as_of_utc": asof.isoformat(),
        "starter": asdict(starter_workload(starter_rows, as_of=asof)),
        "bullpen": asdict(bullpen_workload(bullpen_rows, as_of=asof)),
        "statcast": asdict(rolling_statcast(statcast_rows, as_of=asof)),
        "platoon": asdict(platoon_features(**dict(platoon))),
    }
    assert_no_market_contamination(payload)
    payload["feature_contract_sha256"] = canonical_json_sha256(payload)
    return payload
