"""Flag large screenshot-style line moves. Presentation only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "mlb_quote_move_guard.json"
REASON = "QUOTE_MOVE_NEEDS_CONFIRM"
STATUS = "NEEDS_CONFIRM"


def load_move_guard(path: Path | None = None) -> dict[str, Any]:
    raw = json.loads((path or CONFIG_PATH).read_text())
    thresholds = raw["thresholds"]
    if int(thresholds["ml_american_cents"]) != 40:
        raise ValueError("MLB_QUOTE_MOVE_GUARD_DRIFT")
    if float(thresholds["total_runs"]) != 1.0:
        raise ValueError("MLB_QUOTE_MOVE_GUARD_DRIFT")
    if thresholds["rl_favorite_flip"] is not True:
        raise ValueError("MLB_QUOTE_MOVE_GUARD_DRIFT")
    return raw


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market") or row.get("market_type") or "").upper()


def _game_key(row: Mapping[str, Any]) -> str:
    pk = row.get("game_pk")
    if pk not in (None, ""):
        return str(pk)
    return str(row.get("game_id") or "")


def _price(row: Mapping[str, Any]) -> float | None:
    return _f(row.get("american_odds") if row.get("american_odds") is not None else row.get("price"))


def _index_prior(prior: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    out: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in prior:
        key = (_game_key(row), _market(row))
        if not key[0] or not key[1]:
            continue
        out[key] = row
    return out


def move_reason(current: Mapping[str, Any], previous: Mapping[str, Any], thresholds: Mapping[str, Any]) -> str | None:
    market = _market(current)
    if market != _market(previous):
        return None
    if market in {"MONEYLINE", "F5_MONEYLINE"}:
        new_p, old_p = _price(current), _price(previous)
        if new_p is None or old_p is None:
            return None
        if abs(new_p - old_p) >= float(thresholds["ml_american_cents"]):
            return REASON
        return None
    if market in {"TOTALS", "TEAM_TOTALS", "F5_TOTALS"}:
        new_l, old_l = _f(current.get("line")), _f(previous.get("line"))
        if new_l is None or old_l is None:
            return None
        if abs(new_l - old_l) >= float(thresholds["total_runs"]):
            return REASON
        return None
    if market in {"RUN_LINE", "F5_RUN_LINE"} and thresholds["rl_favorite_flip"]:
        new_l, old_l = _f(current.get("line")), _f(previous.get("line"))
        if new_l is None or old_l is None:
            return None
        # Away-listed line sign flip = favorite flipped.
        if new_l * old_l < 0:
            return REASON
    return None


def apply_quote_move_guard(
    rows: list[dict[str, Any]],
    prior: Sequence[Mapping[str, Any]] | None,
    *,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not prior:
        return rows
    cfg = dict(config or load_move_guard())
    thresholds = cfg["thresholds"]
    lookup = _index_prior(prior)
    for row in rows:
        previous = lookup.get((_game_key(row), _market(row)))
        if previous is None:
            continue
        reason = move_reason(row, previous, thresholds)
        if not reason:
            continue
        if str(row.get("status") or "").upper() == "ACTIONABLE":
            row["status"] = STATUS
        if str(row.get("scored_status") or "").upper() == "ACTIONABLE":
            row["scored_status"] = STATUS
        codes = tuple(row.get("presentation_reason_codes") or ())
        if reason not in codes:
            row["presentation_reason_codes"] = codes + (reason,)
    return rows
