"""Frozen governance policy for LIVE_ENGINE_V1."""

from __future__ import annotations

from dataclasses import dataclass


LIVE_POLICY_VERSION = "LIVE_POLICY_V1"
LIVE_STATE_TTL_SECONDS = 30
LIVE_QUOTE_TTL_SECONDS = 20

# These feature names are forbidden from governed LIVE Model_P unless a future
# policy version explicitly promotes and validates them as model features.
FORBIDDEN_LIVE_MODEL_FEATURES = frozenset({
    "live_odds",
    "live_line",
    "live_price",
    "live_market_probability",
    "market_no_vig_probability",
    "line_movement",
    "steam",
    "ticket_pct",
    "money_pct",
    "handle_pct",
    "public_pct",
    "consensus_pct",
    "sportsbook_projection",
    "handicapper_pick",
    "social_sentiment",
})


@dataclass(frozen=True)
class LiveTTLPolicy:
    version: str = LIVE_POLICY_VERSION
    state_ttl_seconds: int = LIVE_STATE_TTL_SECONDS
    quote_ttl_seconds: int = LIVE_QUOTE_TTL_SECONDS

    def validate(self) -> None:
        if self.version != LIVE_POLICY_VERSION:
            raise ValueError("unrecognized live policy version")
        if self.state_ttl_seconds != LIVE_STATE_TTL_SECONDS:
            raise ValueError("LIVE state TTL is frozen in LIVE_POLICY_V1")
        if self.quote_ttl_seconds != LIVE_QUOTE_TTL_SECONDS:
            raise ValueError("LIVE quote TTL is frozen in LIVE_POLICY_V1")


def assert_market_blind(features: dict | object) -> None:
    keys = set(features.keys()) if hasattr(features, "keys") else set()
    forbidden = sorted(keys & FORBIDDEN_LIVE_MODEL_FEATURES)
    if forbidden:
        raise ValueError("forbidden market-derived LIVE Model_P features: " + ", ".join(forbidden))
