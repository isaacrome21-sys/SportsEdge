"""Secret-safe football live-odds deployment readiness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass(frozen=True)
class FootballLiveOddsReadiness:
    ready: bool
    key_slots: int
    reason: str


def football_live_odds_ready(env: Mapping[str, Any]) -> FootballLiveOddsReadiness:
    keys = []
    primary = env.get("ODDS_API_KEY")
    if isinstance(primary, str) and primary.strip():
        keys.append(primary.strip())
    extra = env.get("ODDS_API_KEYS")
    if isinstance(extra, str):
        keys.extend([x.strip() for x in extra.split(",") if x.strip()])
    unique = tuple(dict.fromkeys(keys))
    if not unique:
        return FootballLiveOddsReadiness(False, 0, "ODDS_API_KEY_MISSING")
    # Never retain or expose credential contents in the readiness object.
    return FootballLiveOddsReadiness(True, len(unique), "READY")


def football_deployment_unblocked(stage: str, env: Mapping[str, Any]) -> bool:
    """A promoted lane may reach live deployment only when credentials exist."""
    return stage == "DEPLOYED" and football_live_odds_ready(env).ready
