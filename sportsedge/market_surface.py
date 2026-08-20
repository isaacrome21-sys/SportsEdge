"""Declared MLB market coverage surface and composed health states."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFECT_ACQUISITION = {"ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"}
DEFECT_ENGINE = {"INPUT_MISSING", "ENGINE_BLOCKED"}


@dataclass(frozen=True)
class MarketSurfaceEntry:
    market: str
    scope: str
    provider_expected: bool
    retry_eligible: bool
    terminal_if_absent: str
    availability_window: Mapping[str, Any]


@dataclass(frozen=True)
class MarketSlot:
    game_id: str
    market: str
    scope: str
    acquisition_state: str
    retry_eligible: bool
    engine_state: str | None
    decision: str | None
    reason: str | None = None


def _window_minutes(window: Mapping[str, Any]) -> tuple[float, float]:
    try:
        opens = float(window["opens_minutes_before_first_pitch"])
        terminal = float(window["terminal_minutes_before_first_pitch"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("MARKET_SURFACE_AVAILABILITY_WINDOW_INVALID") from exc
    if not isfinite(opens) or not isfinite(terminal) or opens < 0 or terminal < 0 or opens < terminal:
        raise ValueError("MARKET_SURFACE_AVAILABILITY_WINDOW_INVALID")
    return opens, terminal


def load_market_surface(path: str = "config/mlb_market_surface.json") -> tuple[str, list[MarketSurfaceEntry]]:
    raw = json.loads(Path(path).read_text())
    version = str(raw.get("version", ""))
    if not version:
        raise ValueError("MARKET_SURFACE_VERSION_MISSING")
    entries = []
    seen = set()
    for row in raw.get("markets", []):
        market = str(row.get("market", "")).strip()
        if not market or market in seen:
            raise ValueError("MARKET_SURFACE_DUPLICATE_OR_MISSING")
        seen.add(market)
        terminal = str(row.get("terminal_if_absent", ""))
        if terminal not in {"ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"}:
            raise ValueError("MARKET_SURFACE_TERMINAL_STATE_INVALID")
        window = row.get("availability_window")
        if not isinstance(window, Mapping):
            raise ValueError("MARKET_SURFACE_AVAILABILITY_WINDOW_INVALID")
        _window_minutes(window)
        entries.append(MarketSurfaceEntry(
            market=market,
            scope=str(row.get("scope", "")),
            provider_expected=bool(row.get("provider_expected")),
            retry_eligible=bool(row.get("retry_eligible")),
            terminal_if_absent=terminal,
            availability_window=dict(window),
        ))
    return version, entries


def _minutes_to_first_pitch(now: datetime, first_pitch_at: datetime) -> float:
    if now.tzinfo is None or first_pitch_at.tzinfo is None:
        raise ValueError("MARKET_SURFACE_TIMEZONE_REQUIRED")
    return (first_pitch_at - now).total_seconds() / 60.0


def _absent_state(entry: MarketSurfaceEntry, *, now: datetime, first_pitch_at: datetime) -> tuple[str, bool]:
    if not entry.provider_expected:
        return "PROVIDER_UNSUPPORTED", False
    minutes = _minutes_to_first_pitch(now, first_pitch_at)
    opens_minutes, terminal_minutes = _window_minutes(entry.availability_window)
    if entry.retry_eligible and (minutes > opens_minutes or minutes > terminal_minutes):
        return "NOT_OFFERED", True
    return entry.terminal_if_absent, False


def build_market_slots(
    *,
    surface: Iterable[MarketSurfaceEntry],
    game_id: str,
    first_pitch_at: datetime,
    now: datetime,
    offered_markets: set[str],
    engine_markets: set[str],
    input_missing_markets: set[str],
    engine_blocked_markets: set[str],
    decisions: Mapping[str, str] | None = None,
) -> list[MarketSlot]:
    decisions = decisions or {}
    slots: list[MarketSlot] = []
    for entry in surface:
        market = entry.market
        if market not in offered_markets:
            acq, retry = _absent_state(entry, now=now, first_pitch_at=first_pitch_at)
            slots.append(MarketSlot(str(game_id), market, entry.scope, acq, retry, None, None))
            continue
        if market not in engine_markets:
            engine_state = "NO_ENGINE"
        elif market in input_missing_markets:
            engine_state = "INPUT_MISSING"
        elif market in engine_blocked_markets:
            engine_state = "ENGINE_BLOCKED"
        else:
            engine_state = "PRICED"
        decision = decisions.get(market) if engine_state == "PRICED" else None
        if decision is not None and decision not in {"BET", "PASS"}:
            raise ValueError("MARKET_SURFACE_DECISION_INVALID")
        slots.append(MarketSlot(str(game_id), market, entry.scope, "OFFERED", False, engine_state, decision))
    return slots


def compose_run_status(slots: Iterable[MarketSlot], *, acquisition_failed_entirely: bool = False) -> str:
    slots = list(slots)
    if acquisition_failed_entirely:
        return "BLOCKED"
    for slot in slots:
        if slot.acquisition_state in DEFECT_ACQUISITION or slot.engine_state in DEFECT_ENGINE:
            return "DEGRADED"
    return "READY"


def compose_card_status(slots: Iterable[MarketSlot]) -> str:
    return "BETS_FOUND" if any(slot.decision == "BET" for slot in slots) else "NO_BETS"
