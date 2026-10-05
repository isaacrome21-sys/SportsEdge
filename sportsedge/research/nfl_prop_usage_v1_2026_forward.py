"""Fail-closed selector for the frozen 2026 NFL prop V1 forward window."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

LOCK_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "research"
    / "nfl_prop_usage_v1_2026_forward_validation_lock.json"
)


class NflPropForwardError(ValueError):
    pass


def load_lock(path: Path | None = None) -> dict[str, Any]:
    value = json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))
    if value.get("schema") != "SPORTSEDGE_NFL_PROP_USAGE_V1_2026_FORWARD_VALIDATION_LOCK":
        raise NflPropForwardError("NFL_PROP_FORWARD_LOCK_SCHEMA_INVALID")
    if value.get("status") != "FROZEN_BEFORE_FORWARD_WEEK5_EVIDENCE":
        raise NflPropForwardError("NFL_PROP_FORWARD_LOCK_STATUS_INVALID")
    return value


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except (TypeError, ValueError) as exc:
        raise NflPropForwardError(f"{field}:TIMESTAMP_REQUIRED") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise NflPropForwardError(f"{field}:TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _num(value: Any, field: str) -> float:
    if value in (None, "") or isinstance(value, bool):
        raise NflPropForwardError(f"{field}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropForwardError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPropForwardError(f"{field}:FINITE_REQUIRED")
    return out


def classify_snapshot(
    row: Mapping[str, Any],
    *,
    lock: Mapping[str, Any] | None = None,
    lock_merged_at: Any,
) -> dict[str, Any]:
    """Validate one genuinely forward DraftKings pair and classify its window."""
    cfg = dict(lock or load_lock())
    window = cfg["forward_window"]
    season = int(_num(row.get("season"), "season"))
    week = int(_num(row.get("week"), "week"))
    if season != int(window["season"]):
        raise NflPropForwardError("SEASON_NOT_FORWARD_WINDOW")
    if not int(window["first_eligible_week"]) <= week <= int(window["last_eligible_week"]):
        raise NflPropForwardError("WEEK_NOT_FORWARD_WINDOW")

    kickoff = _utc(row.get("kickoff_at"), "kickoff_at")
    observed = _utc(row.get("observed_at"), "observed_at")
    captured = _utc(row.get("captured_at"), "captured_at")
    activated = _utc(lock_merged_at, "lock_merged_at")
    first_kick = _utc(window["first_eligible_kickoff_utc"], "first_eligible_kickoff_utc")
    if kickoff < first_kick:
        raise NflPropForwardError("KICKOFF_BEFORE_FORWARD_BOUNDARY")
    if captured < activated or observed < activated:
        raise NflPropForwardError("PRELOCK_EVIDENCE_FORBIDDEN")
    if observed > captured:
        raise NflPropForwardError("OBSERVED_AFTER_CAPTURE_INVALID")
    if observed >= kickoff or captured >= kickoff:
        raise NflPropForwardError("POSTKICK_EVIDENCE_FORBIDDEN")

    book = str(row.get("book") or "").strip().lower()
    if book != str(cfg["decision_snapshot"]["book"]).lower():
        raise NflPropForwardError("BOOK_NOT_FROZEN_DRAFTKINGS")
    market = str(row.get("market") or "").strip()
    allowed = {
        str(spec["provider_market"])
        for spec in (cfg.get("markets") or {}).values()
    }
    if market not in allowed:
        raise NflPropForwardError("MARKET_NOT_FROZEN_V1")
    if not str(row.get("game_id") or "").strip():
        raise NflPropForwardError("GAME_ID_REQUIRED")
    if not str(row.get("player_id") or "").strip():
        raise NflPropForwardError("PLAYER_ID_REQUIRED")
    _num(row.get("line"), "line")
    _num(row.get("over_odds"), "over_odds")
    _num(row.get("under_odds"), "under_odds")

    lead_minutes = (kickoff - observed).total_seconds() / 60.0
    dwin = cfg["decision_snapshot"]["snapshot_window_minutes_before_kickoff"]
    cwin = cfg["close_snapshot"]["snapshot_window_minutes_before_kickoff"]
    lane = None
    if float(dwin["exclusive_min"]) < lead_minutes <= float(dwin["inclusive_max"]):
        lane = "DECISION"
    elif float(cwin["exclusive_min"]) < lead_minutes <= float(cwin["inclusive_max"]):
        lane = "CLOSE"
    else:
        raise NflPropForwardError("SNAPSHOT_OUTSIDE_FROZEN_WINDOWS")
    return {
        **dict(row),
        "season": season,
        "week": week,
        "book": book,
        "observed_at": observed.isoformat(),
        "captured_at": captured.isoformat(),
        "kickoff_at": kickoff.isoformat(),
        "lead_minutes": lead_minutes,
        "forward_lane": lane,
        "admissible": True,
    }


def select_forward_pairs(
    rows: Sequence[Mapping[str, Any]],
    *,
    lock: Mapping[str, Any] | None = None,
    lock_merged_at: Any,
) -> dict[str, Any]:
    """Select latest admissible decision and close row per game/player/market."""
    cfg = dict(lock or load_lock())
    grouped: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = {}
    rejected: list[dict[str, Any]] = []
    for raw in rows:
        try:
            row = classify_snapshot(raw, lock=cfg, lock_merged_at=lock_merged_at)
        except (NflPropForwardError, TypeError, ValueError) as exc:
            rejected.append({"row": dict(raw), "reason": str(exc)})
            continue
        key = (str(row["game_id"]), str(row["player_id"]), str(row["market"]))
        grouped.setdefault(key, {"DECISION": [], "CLOSE": []})[row["forward_lane"]].append(row)

    selected = []
    for key, lanes in sorted(grouped.items()):
        decision = max(lanes["DECISION"], key=lambda r: r["observed_at"]) if lanes["DECISION"] else None
        close = max(lanes["CLOSE"], key=lambda r: r["observed_at"]) if lanes["CLOSE"] else None
        if decision is None:
            rejected.append({
                "key": list(key),
                "reason": "DECISION_SNAPSHOT_REQUIRED_FOR_VALIDATION_ROW",
            })
            continue
        selected.append({
            "game_id": key[0],
            "player_id": key[1],
            "market": key[2],
            "decision": decision,
            "close": close,
            "validation_row_eligible": True,
            "clv_row_eligible": close is not None,
        })
    return {
        "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_2026_FORWARD_SELECTION_V1",
        "selected": selected,
        "rejected": rejected,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


__all__ = [
    "NflPropForwardError",
    "classify_snapshot",
    "load_lock",
    "select_forward_pairs",
]
