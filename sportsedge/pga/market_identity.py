from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re


@dataclass(frozen=True)
class MarketIdentity:
    market_type: str
    round_number: int | None
    selection: str
    line: float | None = None
    opponent: str | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if not str(self.market_type).strip() or not str(self.selection).strip():
            raise ValueError("PGA_MARKET_IDENTITY_REQUIRED")
        if self.round_number is not None and (type(self.round_number) is not int or self.round_number < 1 or self.round_number > 4):
            raise ValueError("PGA_MARKET_ROUND_INVALID")
        if self.line is not None and (isinstance(self.line, bool) or not isinstance(self.line, (int, float)) or not isfinite(float(self.line))):
            raise ValueError("PGA_MARKET_LINE_INVALID")
        if self.opponent is not None and not str(self.opponent).strip():
            raise ValueError("PGA_MARKET_OPPONENT_INVALID")


def normalize_player_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name).strip())
    if not cleaned:
        raise ValueError("PGA_PLAYER_NAME_REQUIRED")
    return cleaned.casefold()


def canonical_market_key(identity: MarketIdentity) -> str:
    """Selection-specific wager identity."""
    parts = [
        identity.market_type.strip().casefold(),
        str(identity.round_number) if identity.round_number is not None else "event",
        normalize_player_name(identity.selection),
        "" if identity.line is None else f"{float(identity.line):g}",
        "" if identity.opponent is None else normalize_player_name(identity.opponent),
        "" if identity.scope is None else identity.scope.strip().casefold(),
    ]
    return "|".join(parts)


def canonical_market_group_key(identity: MarketIdentity) -> str:
    """Market-family identity used to pair opposite H2H sides or full-field outcomes."""
    market = identity.market_type.strip().casefold()
    scope = "" if identity.scope is None else identity.scope.strip().casefold()
    round_key = str(identity.round_number) if identity.round_number is not None else "event"
    line = "" if identity.line is None else f"{float(identity.line):g}"
    if identity.opponent is not None:
        participants = sorted((normalize_player_name(identity.selection), normalize_player_name(identity.opponent)))
        participant_key = "~".join(participants)
    elif market in {"outright", "winner", "first_round_leader", "frl"}:
        participant_key = "FIELD"
    else:
        participant_key = normalize_player_name(identity.selection)
    return "|".join((market, round_key, participant_key, line, scope))


def assert_same_market(a: MarketIdentity, b: MarketIdentity, *, selection_specific: bool = True) -> None:
    if type(selection_specific) is not bool:
        raise ValueError("PGA_SELECTION_SPECIFIC_MUST_BE_BOOL")
    left = canonical_market_key(a) if selection_specific else canonical_market_group_key(a)
    right = canonical_market_key(b) if selection_specific else canonical_market_group_key(b)
    if left != right:
        raise ValueError(f"market identity mismatch: {left} != {right}")
