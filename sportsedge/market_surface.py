"""Declared MLB market-surface coverage and run-health composition.

Market identity is owned by ``config/mlb_market_catalog.json``. The surface file
adds acquisition/runtime metadata for those identities and must match the
canonical catalog exactly when loaded through the production path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_MARKET_SURFACE_PATH = "config/mlb_market_surface.json"
DEFAULT_MLB_MARKET_CATALOG_PATH = "config/mlb_market_catalog.json"

RUN_STATES = frozenset({"READY", "DEGRADED", "BLOCKED"})
ACQUISITION_STATES = frozenset({"OFFERED", "NOT_OFFERED", "ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"})
ENGINE_STATES = frozenset({"PRICED", "NO_ENGINE", "INPUT_MISSING", "ENGINE_BLOCKED"})
DECISION_STATES = frozenset({"BET", "PASS"})
CARD_STATES = frozenset({"BETS_FOUND", "NO_BETS"})
DEFECT_ACQUISITION_STATES = frozenset({"ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED"})
DEFECT_ENGINE_STATES = frozenset({"INPUT_MISSING", "ENGINE_BLOCKED"})


class MarketSurfaceError(ValueError):
    pass


@dataclass(frozen=True)
class MarketSpec:
    market: str
    scope: str
    provider_expected: bool
    retry_eligible: bool
    terminal_if_absent: str
    opens_minutes_before_first_pitch: float
    expected_by_minutes_before_first_pitch: float


@dataclass(frozen=True)
class CoverageSlot:
    game_id: str
    market: str
    scope: str
    acquisition_status: str
    engine_status: str
    decision_status: str | None
    retry_eligible: bool
    reason: str


def _load_canonical_market_ids(path: str | Path) -> set[str]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise MarketSurfaceError("MLB_MARKET_CATALOG_NOT_OBJECT")
    out: set[str] = set()
    for key, rows in raw.items():
        if key == "schema_version" or not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, str):
                market = row
            elif isinstance(row, Mapping):
                market = str(row.get("market") or "")
            else:
                market = ""
            if not market or market in out:
                raise MarketSurfaceError("MLB_MARKET_CATALOG_IDENTITY_INVALID")
            out.add(market)
    if not out:
        raise MarketSurfaceError("MLB_MARKET_CATALOG_EMPTY")
    return out


def load_market_surface(
    path: str | Path = DEFAULT_MARKET_SURFACE_PATH,
    *,
    catalog_path: str | Path | None = DEFAULT_MLB_MARKET_CATALOG_PATH,
) -> tuple[str, tuple[MarketSpec, ...]]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise MarketSurfaceError("MARKET_SURFACE_NOT_OBJECT")
    version = str(raw.get("version") or "")
    rows = raw.get("markets")
    if not version or not isinstance(rows, list) or not rows:
        raise MarketSurfaceError("MARKET_SURFACE_MALFORMED")
    out: list[MarketSpec] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise MarketSurfaceError("MARKET_SURFACE_ROW_MALFORMED")
        market = str(row.get("market") or "")
        scope = str(row.get("scope") or "")
        if not market or not scope or market in seen:
            raise MarketSurfaceError("MARKET_SURFACE_IDENTITY_INVALID")
        seen.add(market)
        window = row.get("availability_window")
        if not isinstance(window, Mapping):
            raise MarketSurfaceError("MARKET_SURFACE_WINDOW_MALFORMED")
        opens = float(window.get("opens_minutes_before_first_pitch"))
        expected_by = float(window.get("expected_by_minutes_before_first_pitch"))
        if opens < 0 or expected_by < 0 or expected_by > opens:
            raise MarketSurfaceError("MARKET_SURFACE_WINDOW_INVALID")
        terminal = str(row.get("terminal_if_absent") or "")
        if terminal not in {"ACQUISITION_MISSING", "PROVIDER_UNSUPPORTED", "NOT_OFFERED"}:
            raise MarketSurfaceError("MARKET_SURFACE_TERMINAL_INVALID")
        out.append(MarketSpec(
            market=market,
            scope=scope,
            provider_expected=bool(row.get("provider_expected")),
            retry_eligible=bool(row.get("retry_eligible")),
            terminal_if_absent=terminal,
            opens_minutes_before_first_pitch=opens,
            expected_by_minutes_before_first_pitch=expected_by,
        ))

    if catalog_path is not None:
        canonical = _load_canonical_market_ids(catalog_path)
        if seen != canonical:
            missing = sorted(canonical - seen)
            extra = sorted(seen - canonical)
            raise MarketSurfaceError(
                f"MARKET_SURFACE_CATALOG_MISMATCH missing={missing} extra={extra}"
            )
    return version, tuple(out)


def classify_absent_market(spec: MarketSpec, *, now: datetime, first_pitch: datetime) -> tuple[str, bool, str]:
    if now.tzinfo is None or first_pitch.tzinfo is None:
        raise MarketSurfaceError("TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    first_pitch = first_pitch.astimezone(timezone.utc)
    minutes = (first_pitch - now).total_seconds() / 60.0
    if not spec.provider_expected:
        return "PROVIDER_UNSUPPORTED", False, "DECLARED_PROVIDER_UNSUPPORTED"
    if minutes < 0:
        return "ACQUISITION_MISSING", False, "FIRST_PITCH_PASSED"
    if spec.retry_eligible and minutes > spec.expected_by_minutes_before_first_pitch:
        # Market is allowed to be absent before its expected-posting deadline.
        return "NOT_OFFERED", True, "WITHIN_RETRY_WINDOW"
    if spec.terminal_if_absent == "NOT_OFFERED":
        return "NOT_OFFERED", False, "TERMINAL_NOT_OFFERED"
    return spec.terminal_if_absent, False, "EXPECTED_MARKET_ABSENT"


def compose_run_status(slots: Iterable[CoverageSlot], *, infrastructure_blocked: bool = False) -> str:
    if infrastructure_blocked:
        return "BLOCKED"
    rows = tuple(slots)
    if any(x.acquisition_status in DEFECT_ACQUISITION_STATES or x.engine_status in DEFECT_ENGINE_STATES for x in rows):
        return "DEGRADED"
    return "READY"


def compose_card_status(decisions: Iterable[str | None]) -> str:
    return "BETS_FOUND" if any(x == "BET" for x in decisions) else "NO_BETS"


def build_market_grid(
    *,
    games: Iterable[tuple[str, datetime]],
    specs: Iterable[MarketSpec],
    quotes: Iterable[Mapping[str, Any]],
    engine_capable_markets: frozenset[str] | set[str],
    feature_failures: Mapping[tuple[str, str, str], str] | None = None,
    result_rows: Iterable[Any] = (),
    now: datetime,
) -> tuple[CoverageSlot, ...]:
    feature_failures = feature_failures or {}
    offered_by_game_market: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for quote in quotes:
        key = (str(quote.get("game_id")), str(quote.get("market")))
        offered_by_game_market.setdefault(key, []).append(quote)

    result_by_game_market: dict[tuple[str, str], list[Any]] = {}
    for row in result_rows:
        key = (str(getattr(row, "game_id", "")), str(getattr(row, "market", "")))
        result_by_game_market.setdefault(key, []).append(row)

    out: list[CoverageSlot] = []
    for game_id, first_pitch in games:
        for spec in specs:
            offered = offered_by_game_market.get((str(game_id), spec.market), [])
            if not offered:
                acquisition, retry, reason = classify_absent_market(spec, now=now, first_pitch=first_pitch)
                out.append(CoverageSlot(str(game_id), spec.market, spec.scope, acquisition, "NO_ENGINE", None, retry, reason))
                continue

            if spec.market not in engine_capable_markets:
                out.append(CoverageSlot(str(game_id), spec.market, spec.scope, "OFFERED", "NO_ENGINE", None, False, "MARKET_ENGINE_UNREGISTERED"))
                continue

            identities = [(str(q.get("game_id")), str(q.get("entity_id")), str(q.get("market"))) for q in offered]
            missing = [feature_failures[i] for i in identities if i in feature_failures]
            if missing:
                out.append(CoverageSlot(str(game_id), spec.market, spec.scope, "OFFERED", "INPUT_MISSING", None, False, missing[0]))
                continue

            rows = result_by_game_market.get((str(game_id), spec.market), [])
            if rows and all(str(getattr(r, "bet_status", "")) == "BLOCKED" for r in rows):
                out.append(CoverageSlot(str(game_id), spec.market, spec.scope, "OFFERED", "ENGINE_BLOCKED", None, False, str(getattr(rows[0], "reason", "ENGINE_BLOCKED"))))
                continue

            if not rows:
                out.append(CoverageSlot(str(game_id), spec.market, spec.scope, "OFFERED", "NO_ENGINE", None, False, "OFFERED_MARKET_NOT_PRICED"))
                continue

            decision = "BET" if any(str(getattr(r, "bet_status", "")) in {"BET", "OFFICIAL_BET"} for r in rows) else "PASS"
            out.append(CoverageSlot(str(game_id), spec.market, spec.scope, "OFFERED", "PRICED", decision, False, "PRICED"))
    return tuple(out)
