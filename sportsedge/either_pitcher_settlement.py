"""Either-Pitcher structural outcome helpers and fail-closed book settlement gate.

The active joint engine currently defines each side independently with OR semantics:
OVER wins when either pitcher is above the line and UNDER wins when either pitcher
is below the line. Those events overlap for cross-states (for example 7 and 4 at
5.5), so they are not a normalized opposite-side sportsbook contract.

`settle_either_pitcher_engine_semantics` is retained only for structural parity
checks against the candidate engine. `settle_either_pitcher` deliberately fails
closed until validated sportsbook evidence defines the actual proposition and
void/push semantics required by the acceptance matrix.
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


def settle_either_pitcher_engine_semantics(
    facts: Mapping[str, Any],
    *,
    market: str,
    entity_id: Any,
    line: Any,
    side: Any,
) -> str:
    """Mirror the candidate engine's current OR/OR semantics for structural tests only."""
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


def settle_either_pitcher(
    facts: Mapping[str, Any],
    *,
    market: str,
    entity_id: Any,
    line: Any,
    side: Any,
) -> str:
    """Fail closed until book-specific Either-Pitcher semantics are normalized."""
    # Validate the canonical shape enough to prevent malformed rows from being
    # mistaken for a policy-only block, but do not infer sportsbook semantics.
    market = str(market or "").upper()
    if market not in EITHER_PITCHER_MARKETS:
        raise EitherPitcherSettlementError(f"unsupported either-pitcher market:{market}")
    parse_pair_entity_id(entity_id)
    _line(line)
    direction = str(side or "").upper()
    if direction not in {"OVER", "UNDER"}:
        raise EitherPitcherSettlementError("side must be OVER or UNDER")
    raise EitherPitcherSettlementError("EITHER_PITCHER_BOOK_SPECIFIC_SEMANTICS_REQUIRED")
