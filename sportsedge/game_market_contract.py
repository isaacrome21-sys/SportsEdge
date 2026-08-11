"""Fail-closed deployment contract for MLB game markets.

This module does not calculate Model_P.  It records the accepted deployment
eligibility recovered from the SportsEdge legacy validation registry so current
live-card plumbing can recognize game-market families without silently promoting
unvalidated math.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameMarketPolicy:
    canonical_market: str
    period: str
    official_eligible: bool
    validation_status: str
    reason: str


_POLICIES = {
    "ML": GameMarketPolicy(
        "ML", "FG", True, "PASS_BETA",
        "Frozen beta anchor is executable; beta penalty remains in grading.",
    ),
    "RL": GameMarketPolicy(
        "RL", "FG", False, "BLOCKED_DEPLOYMENT_PARITY",
        "Deployed run-distribution parity with the accepted run-line validation artifact is not proven.",
    ),
    "TOTAL": GameMarketPolicy(
        "TOTAL", "FG", False, "BLOCKED_FRESH_CALIBRATION",
        "Full-game total distribution requires fresh independent calibration before official release.",
    ),
    "NRFI": GameMarketPolicy(
        "NRFI", "1ST", True, "PASS_GATED",
        "Direct first-inning model artifact required; accepted registry status is PASS_GATED.",
    ),
    "YRFI": GameMarketPolicy(
        "YRFI", "1ST", True, "PASS_GATED",
        "Direct first-inning model artifact required; accepted registry status is PASS_GATED.",
    ),
}


def canonical_game_market(value: str) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "MONEYLINE": "ML",
        "MONEY_LINE": "ML",
        "H2H": "ML",
        "RUNLINE": "RL",
        "RUN_LINE": "RL",
        "SPREAD": "RL",
        "SPREADS": "RL",
        "TOTALS": "TOTAL",
        "GAME_TOTAL": "TOTAL",
        "NO_RUN_FIRST_INNING": "NRFI",
        "YES_RUN_FIRST_INNING": "YRFI",
    }
    return aliases.get(text, text)


def game_market_policy(value: str) -> GameMarketPolicy:
    market = canonical_game_market(value)
    try:
        return _POLICIES[market]
    except KeyError as exc:
        raise ValueError(f"UNSUPPORTED_GAME_MARKET:{market}") from exc


def recognized_game_markets() -> frozenset[str]:
    return frozenset(_POLICIES)


def require_official_eligibility(value: str) -> GameMarketPolicy:
    policy = game_market_policy(value)
    if not policy.official_eligible:
        raise ValueError(f"MARKET_VALIDATION_BLOCK:{policy.validation_status}:{policy.canonical_market}")
    return policy
