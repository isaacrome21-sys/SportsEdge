"""Deterministic outcome interpreter for canonical Either-Pitcher count markets.

This module mirrors the active joint engine semantics exactly. It does not decide
whether a sportsbook rule is valid; the catalog settlement gate must validate the
book-specific rule before calling this interpreter.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

EITHER_PITCHER_MARKETS = frozenset({
    "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER",
})
_FIELD_BY_MARKET = {
    "EITHER_PITCHER_HITS_ALLOWED": "hits_allowed",
    "EITHER_PITCHER_BB": "walks_allowed",
    "EITHER_PITCHER_ER": "earned_runs",
}


class EitherPitcherSettlementError(ValueError):
    pass


def parse_pair_entity_id(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    parts = text.split("|")
    if len(parts) != 2:
        raise EitherPitcherSettlementError("EITHER_PITCHER_ENTITY_ID_MUST_BE_AWAY_PIPE_HOME")
    out = []
    for part in parts:
        token = part.strip()
        if not token.isdigit() or int(token) <= 0:
            raise EitherPitcherSettlementError("EITHER_PITCHER_ENTITY_ID_INVALID")
        out.append(str(int(token)))
    if out[0] == out[1]:
        raise EitherPitcherSettlementError("EITHER_PITCHER_ENTITY_IDS_MUST_DIFFER")
    return out[0], out[1]


def _line(value: Any) -> float:
    if isinstance(value, bool):
        raise EitherPitcherSettlementError("line must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise EitherPitcherSettlementError("line must be finite numeric") from exc
    if not isfinite(out) or out < 0:
        raise EitherPitcherSettlementError("line must be finite and >= 0")
    return out


def _pitcher_value(rows: Any, pitcher_id: str, field: str) -> float:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise EitherPitcherSettlementError("official pitcher facts missing")
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and str(row.get("player_id") or "") == pitcher_id
    ]
    if len(matches) != 1 or field not in matches[0]:
        raise EitherPitcherSettlementError(f"official pitcher fact missing:{pitcher_id}:{field}")
    try:
        value = float(matches[0][field])
    except (TypeError, ValueError) as exc:
        raise EitherPitcherSettlementError("official pitcher fact not numeric") from exc
    if not isfinite(value) or value < 0:
        raise EitherPitcherSettlementError("official pitcher fact invalid")
    return value


def settle_either_pitcher(
    facts: Mapping[str, Any],
    *,
    market: str,
    entity_id: Any,
    line: Any,
    side: Any,
) -> str:
    """Return WIN/LOSS/PUSH using the same OR semantics as pitcher_joint_engine."""
    market = str(market or "").upper()
    if market not in EITHER_PITCHER_MARKETS:
        raise EitherPitcherSettlementError(f"unsupported either-pitcher market:{market}")
    away_pitcher_id, home_pitcher_id = parse_pair_entity_id(entity_id)
    threshold = _line(line)
    direction = str(side or "").upper()
    if direction not in {"OVER", "UNDER"}:
        raise EitherPitcherSettlementError("side must be OVER or UNDER")
    field = _FIELD_BY_MARKET[market]
    rows = facts.get("pitchers")
    a = _pitcher_value(rows, away_pitcher_id, field)
    b = _pitcher_value(rows, home_pitcher_id, field)

    if direction == "OVER":
        if a > threshold or b > threshold:
            return "WIN"
        if float(threshold).is_integer() and (a == threshold or b == threshold):
            return "PUSH"
        return "LOSS"

    if a < threshold or b < threshold:
        return "WIN"
    if float(threshold).is_integer() and (a == threshold or b == threshold):
        return "PUSH"
    return "LOSS"
