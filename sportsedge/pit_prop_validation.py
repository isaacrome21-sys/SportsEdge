"""Strict point-in-time row contract for MLB prop challenger validation.

This module does not fetch or synthesize historical odds. It validates that every
comparison row carries the minimum evidence required to call a result historical:
- a quote timestamp before first pitch,
- the actual quoted line/side,
- a realized outcome,
- strictly-prior feature history identity,
- incumbent and challenger probabilities produced from the same observation.

Rows missing any of those fields are rejected rather than downgraded silently to
"diagnostic" evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

from .behavioral_acceptance import analyze_challenger


class PITPropValidationError(ValueError):
    pass


SUPPORTED_MARKETS = frozenset({"PITCHER_OUTS", "PITCHER_ER", "RBI"})


@dataclass(frozen=True)
class PITPropRow:
    market: str
    game_id: str
    entity_id: str
    quote_ts: str
    first_pitch_ts: str
    line: float
    side: str
    realized_count: int
    history_asof_ts: str
    history_source_hash: str
    incumbent_p: float
    challenger_p: float

    @property
    def realized_win(self) -> bool:
        if self.side == "OVER":
            return self.realized_count > self.line
        return self.realized_count < self.line

    @property
    def realized_push(self) -> bool:
        return abs(self.realized_count - self.line) < 1e-12


def _parse_ts(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PITPropValidationError(f"{name} required")
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PITPropValidationError(f"{name} must be ISO-8601") from exc
    if dt.tzinfo is None:
        raise PITPropValidationError(f"{name} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PITPropValidationError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PITPropValidationError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise PITPropValidationError(f"{name} must be finite")
    return out


def _prob(value: Any, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise PITPropValidationError(f"{name} must be in [0,1]")
    return out


def normalize_pit_row(raw: Mapping[str, Any]) -> PITPropRow:
    market = str(raw.get("market", "")).strip().upper()
    if market not in SUPPORTED_MARKETS:
        raise PITPropValidationError(f"unsupported market {market!r}")
    game_id = str(raw.get("game_id", "")).strip()
    entity_id = str(raw.get("entity_id", "")).strip()
    if not game_id or not entity_id:
        raise PITPropValidationError("game_id and entity_id required")

    quote_dt = _parse_ts(raw.get("quote_ts"), "quote_ts")
    first_pitch_dt = _parse_ts(raw.get("first_pitch_ts"), "first_pitch_ts")
    history_dt = _parse_ts(raw.get("history_asof_ts"), "history_asof_ts")
    if quote_dt >= first_pitch_dt:
        raise PITPropValidationError("quote_ts must be before first_pitch_ts")
    if history_dt >= first_pitch_dt:
        raise PITPropValidationError("history_asof_ts must be before first_pitch_ts")

    side = str(raw.get("side", "")).strip().upper()
    if side not in {"OVER", "UNDER"}:
        raise PITPropValidationError("side must be OVER or UNDER")
    line = _finite(raw.get("line"), "line")
    if line < 0:
        raise PITPropValidationError("line must be >= 0")

    realized_raw = raw.get("realized_count")
    if isinstance(realized_raw, bool):
        raise PITPropValidationError("realized_count must be a non-negative integer")
    try:
        realized_count = int(realized_raw)
    except (TypeError, ValueError) as exc:
        raise PITPropValidationError("realized_count must be a non-negative integer") from exc
    if realized_count < 0 or float(realized_count) != float(realized_raw):
        raise PITPropValidationError("realized_count must be a non-negative integer")

    history_source_hash = str(raw.get("history_source_hash", "")).strip()
    if len(history_source_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in history_source_hash):
        raise PITPropValidationError("history_source_hash must be a SHA-256 hex digest")

    return PITPropRow(
        market=market,
        game_id=game_id,
        entity_id=entity_id,
        quote_ts=quote_dt.isoformat(),
        first_pitch_ts=first_pitch_dt.isoformat(),
        line=line,
        side=side,
        realized_count=realized_count,
        history_asof_ts=history_dt.isoformat(),
        history_source_hash=history_source_hash.lower(),
        incumbent_p=_prob(raw.get("incumbent_p"), "incumbent_p"),
        challenger_p=_prob(raw.get("challenger_p"), "challenger_p"),
    )


def analyze_pit_prop_rows(raw_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [normalize_pit_row(row) for row in raw_rows]
    if not rows:
        raise PITPropValidationError("at least one PIT row is required")

    behavioral_rows = []
    pushes = 0
    for row in rows:
        if row.realized_push:
            pushes += 1
            continue
        reference_p = 1.0 if row.realized_win else 0.0
        behavioral_rows.append({
            "market": row.market,
            "line": row.line,
            "side": row.side,
            "reference_p": reference_p,
            "incumbent_p": row.incumbent_p,
            "challenger_p": row.challenger_p,
        })
    if not behavioral_rows:
        raise PITPropValidationError("all PIT rows are pushes; no scored comparison rows")

    report = analyze_challenger(behavioral_rows)
    report.update({
        "pit_schema_version": 1,
        "source_row_count": len(rows),
        "push_rows_excluded_from_binary_error": pushes,
        "markets": sorted({row.market for row in rows}),
        "evidence_class": "HISTORICAL_PIT" if len(rows) > 0 else "UNAVAILABLE",
        "pit_rows": [asdict(row) for row in rows],
    })
    return report
