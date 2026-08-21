from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MarketIdentity:
    market_type: str
    round_number: int | None
    selection: str
    line: float | None = None
    opponent: str | None = None
    scope: str | None = None


def normalize_player_name(name: str) -> str:
    """Normalize player labels for cross-provider matching without alias guessing."""
    cleaned = re.sub(r"\s+", " ", name.strip())
    return cleaned.casefold()


def canonical_market_key(identity: MarketIdentity) -> str:
    parts = [
        identity.market_type.strip().casefold(),
        str(identity.round_number) if identity.round_number is not None else "event",
        normalize_player_name(identity.selection),
        "" if identity.line is None else f"{identity.line:g}",
        "" if identity.opponent is None else normalize_player_name(identity.opponent),
        "" if identity.scope is None else identity.scope.strip().casefold(),
    ]
    return "|".join(parts)


def assert_same_market(a: MarketIdentity, b: MarketIdentity) -> None:
    """Fail closed when two provider records do not describe the same wager."""
    if canonical_market_key(a) != canonical_market_key(b):
        raise ValueError(
            "market identity mismatch: "
            f"{canonical_market_key(a)} != {canonical_market_key(b)}"
        )
